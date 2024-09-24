## Info

This is a *very* experimental branch to add N_m3u8DL-RE as downloader to Devine.
Do not merge this into your master branch!

- DASH: N_m3u8DL-RE will be used as downloader and merger, but leave decryption and muxing to Devine
- HLS: N_m3u8DL-RE will be used as downloader, merger, and decryptor, but leave muxing to Devine
- URL: Not currently supported as N_m3u8DL-RE require a manifest or playlist for parsing
- ISM: Possibly in a future version
- SUBTITLE: Any subtitle will be downloaded using requests since there's no benefit to using N_m3u8DL-RE for it

> [!NOTE]
> `OnSegmentFilter` and `period_filter` will have no effect when using this. Experiment with `ad_keyword` as another option

## Usage:
Set it as downloader in the config file:
```yaml
downloader: n_m3u8dl_re # notice the formatting!
```

Config options:
```yaml
n_m3u8dl_re:
  use_proxy: # set true or false whether to use proxy for downloading. Default: true
  thread_count: # set number of how many threads to use when dowloading. Note that this is for each track, use responsibly
  ad_keyword: # filter out unwanted segments from the manifest
```

## Changelog:

```
- feat(downloaders): Add N_m3u8DL-RE as downloader
- fix(dl): Improve error message output to include ValueError, AttributeError, TypeError
- fix(binaries): Add N_m3u8DL-RE as searchable binary
- feat(config): Add config entries for n_m3u8dl_re as downloader and its options
- feat(track): Add new imports and checks for a new downloader
- feat(DASH): Add download arguments for N_m3u8DL-RE
- feat(HLS): Add download arguments for N_m3u8DL-RE, skip_merge check
- fix(Widevine): Filter out annoying info messages from shaka packager
```

## Licensing

This software is licensed under the terms of [GNU General Public License, Version 3.0](LICENSE).  
You can find a copy of the license in the LICENSE file in the root folder.

* * *

© rlaphoenix 2019-2024
