import logging
import os
import re
import subprocess
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any, Generator, MutableMapping, Optional, Union

from devine.core import binaries
from devine.core.config import config
from devine.core.console import console
from devine.core.constants import DOWNLOAD_CANCELLED

AUDIO_CODEC_MAP = {"AAC": "mp4a", "AC3": "ac-3", "EC3": "ec-3"}
VIDEO_CODEC_MAP = {"AVC": "avc", "HEVC": "hvc", "DV": "dvh"}

def track_selection(track: object) -> list[str]:
    manifest = track.data["dash"]["manifest"]

    track_type = track.__class__.__name__
    codec = track.codec.name
    bitrate = track.bitrate // 1000
    language = track.language
    width = track.width if track_type == "Video" else None
    range = track.range.name if track_type == "Video" else None
    # drm = track.drm[0] if track.drm else None
    # height = track.height if track_type == "Video" else None

    # TODO: is there a better way to determine lang and track_id?
    audio_ids = []
    lang = None
    adaptation_sets = manifest.xpath("//AdaptationSet")
    for adaptation_set in adaptation_sets:
        if adaptation_set.get("mimeType") == "audio/mp4":
            lang = adaptation_set.get("lang")
            representations = adaptation_set.findall(".//Representation")
            for representation in representations:
                track_id = representation.get("id")
                if track_id:
                    audio_ids.append(track_id)

    if track_type == "Audio":
        codecs = AUDIO_CODEC_MAP.get(codec)
        bandwidth = f"bwMin={bitrate}:bwMax={bitrate + 5}"
        if lang:
            audio_selection = ["-sa", f"lang={language}:codecs={codecs}:{bandwidth}"]
        elif not lang and len(audio_ids) == 1:
            audio_selection = ["-sa", f"id={audio_ids[0]}"]
        else:
            audio_selection = ["-sa", "for=best"]
        return audio_selection

    if track_type == "Video":
        # N_m3u8DL-RE lists Dolby Vision as a codec (dvhe) while Devine use range to specify it
        if codec == "HEVC" and range == "DV":
            codec = "DV"
        codecs = VIDEO_CODEC_MAP.get(codec)
        bandwidth = f"bwMin={bitrate}:bwMax={bitrate + 5}"
        video_selection = ["-sv", f"res={width}*:codecs={codecs}:{bandwidth}"]
        return video_selection

def download(
    urls: Union[str, dict[str, Any], list[str], list[dict[str, Any]]],
    track: object,
    output_dir: Path,
    filename: str,
    proxy: Optional[str] = None,
    max_workers: Optional[int] = None,
    content_keys: Optional[dict[str, Any]] = None
) -> Generator[dict[str, Any], None, None]:
    if not urls:
        raise ValueError("urls must be provided and not empty")
    elif not isinstance(urls, (str, dict, list)):
        raise TypeError(f"Expected urls to be {str} or {dict} or a list of one of them, not {type(urls)}")

    if not output_dir:
        raise ValueError("output_dir must be provided")
    elif not isinstance(output_dir, Path):
        raise TypeError(f"Expected output_dir to be {Path}, not {type(output_dir)}")

    if not filename:
        raise ValueError("filename must be provided")
    elif not isinstance(filename, str):
        raise TypeError(f"Expected filename to be {str}, not {type(filename)}")

    if not isinstance(proxy, (str, type(None))):
        raise TypeError(f"Expected proxy to be {str}, not {type(proxy)}")

    if not max_workers:
        max_workers = min(32, (os.cpu_count() or 1) + 4)
    elif not isinstance(max_workers, int):
        raise TypeError(f"Expected max_workers to be {int}, not {type(max_workers)}")

    if not isinstance(urls, list):
        urls = [urls]

    if not binaries.N_m3u8DL_RE:
        raise EnvironmentError("N_m3u8DL-RE executable not found...")

    track_type = track.__class__.__name__
    thread_count = str(config.n_m3u8dl_re.get("thread_count", max_workers))
    ad_keyword = config.n_m3u8dl_re.get("ad_keyword")

    arguments = [
        track.url,
        "--save-dir", output_dir,
        "--tmp-dir", output_dir,
        "--thread-count", thread_count,
        "--no-log",
        "--write-meta-json", "false",
    ]

    if proxy:
        arguments.extend(["--custom-proxy", proxy])

    if content_keys:
        for kid, key in content_keys.items():
            keys = f"{kid.hex}:{key.lower()}"
        arguments.extend(["--key", keys])
        arguments.extend(["--use-shaka-packager"])

    if ad_keyword:
        arguments.extend(["--ad-keyword", ad_keyword])

    if track.descriptor.name == "URL":
        error = f"[N_m3u8DL-RE]: {track.descriptor} is currently not supported"
        raise ValueError(error)
    elif track.descriptor.name == "DASH":
        arguments.extend(track_selection(track))

    # TODO: improve this nonsense
    percent_re = re.compile(r"(\d+\.\d+%)")
    speed_re = re.compile(r"(\d+\.\d+MBps)")
    warn = re.compile(r"(WARN : Response.*)")
    error = re.compile(r"(ERROR.*)")
    size_patterns = [
        re.compile(r"(\d+\.\d+MB/\d+\.\d+GB)"),
        re.compile(r"(\d+\.\d+GB/\d+\.\d+GB)"),
        re.compile(r"(\d+\.\d+MB/\d+\.\d+MB)"),
    ]

    yield dict(total=100)

    try:
        with subprocess.Popen(
            [binaries.N_m3u8DL_RE, *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        ) as p:
            for line in p.stdout:
                output = line.strip()
                if output:
                    percent = percent_re.search(output)
                    speed = speed_re.search(output)
                    size = next(
                        (pattern.search(output).group(1)
                         for pattern in size_patterns
                         if pattern.search(output)), ""
                    )

                    if speed:
                        yield dict(downloaded=f"{speed.group(1)} {size}")
                    if percent:
                        progress = int(percent.group(1).split(".")[0])
                        yield dict(completed=progress) if progress < 100 else dict(downloaded="Merging")

                    if warn.search(output):
                        console.log(f"{track_type} " + warn.search(output).group(1))

            p.wait()

        if p.returncode != 0:
            if error.search(output):
                raise ValueError(f"[N_m3u8DL-RE]: {error.search(output).group(1)}")
            raise subprocess.CalledProcessError(p.returncode, arguments)

    except ConnectionResetError:
        # interrupted while passing URI to download
        raise KeyboardInterrupt()
    except KeyboardInterrupt:
        DOWNLOAD_CANCELLED.set()  # skip pending track downloads
        yield dict(downloaded="[yellow]CANCELLED")
        raise
    except Exception:
        DOWNLOAD_CANCELLED.set()  # skip pending track downloads
        yield dict(downloaded="[red]FAILED")
        raise


def n_m3u8dl_re(
    urls: Union[str, list[str], dict[str, Any], list[dict[str, Any]]],
    track: object,
    output_dir: Path,
    filename: str,
    headers: Optional[MutableMapping[str, Union[str, bytes]]] = None,
    cookies: Optional[Union[MutableMapping[str, str], CookieJar]] = None,
    proxy: Optional[str] = None,
    max_workers: Optional[int] = None,
    content_keys: Optional[dict[str, Any]] = None
) -> Generator[dict[str, Any], None, None]:
    """
    Download files using N_m3u8DL-RE.
    https://github.com/nilaoda/N_m3u8DL-RE

    Yields the following download status updates while chunks are downloading:

    - {total: 100} (100% download total)
    - {completed: 1} (1% download progress out of 100%)
    - {downloaded: "10.1 MB/s"} (currently downloading at a rate of 10.1 MB/s)

    The data is in the same format accepted by rich's progress.update() function.

    Parameters:
        urls: Web URL(s) to file(s) to download. You can use a dictionary with the key
            "url" for the URI, and other keys for extra arguments to use per-URL.
        track: The track to download. Used to get track attributes for the selection
            process. Note that Track.Descriptor.URL is not supported by N_m3u8DL-RE.
        output_dir: The folder to save the file into. If the save path's directory does
            not exist then it will be made automatically.
        filename: The filename or filename template to use for each file. The variables
            you can use are `i` for the URL index and `ext` for the URL extension.
        max_workers: The maximum amount of threads to use for downloads. Defaults to
            min(32,(cpu_count+4)). Can be set in config with --thread-count option.
        content_keys: The content keys to use for decryption.
    """
    track_type = track.__class__.__name__

    log = logging.getLogger("N_m3u8DL-RE")
    if proxy and not config.n_m3u8dl_re.get("use_proxy", True):
        log.warning(f"{track_type}: Ignoring proxy as N_m3u8DL-RE is set to use_proxy=False")
        proxy = None

    yield from download(urls, track, output_dir, filename, proxy, max_workers, content_keys)


__all__ = ("n_m3u8dl_re",)
