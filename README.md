<h1 align="center">RedTube API</h1>

<div align="center">
    <a href="https://pepy.tech/project/redtube_api"><img src="https://static.pepy.tech/badge/redtube_api" alt="Downloads"></a>
    <a href="https://badge.fury.io/py/redtube_api"><img src="https://badge.fury.io/py/redtube_api.svg" alt="PyPI version" height="18"></a>
    <a href="https://echteralsfake.me/ci/redtube_api/badge.svg"><img src="https://echteralsfake.me/ci/redtube_api/badge.svg" alt="API Tests"/></a>
</div>

<br>

> [!CAUTION]
> This is still being worked on, do not use yet!!!!!!!!


# Disclaimer
> [!IMPORTANT]
> This is an unofficial and unaffiliated project. Please read the full disclaimer before use:
> **[DISCLAIMER.md](https://github.com/EchterAlsFake/API_Docs/blob/master/Disclaimer.md)**
>
> By using this project you agree to comply with the target site’s rules, copyright/licensing requirements,
> and applicable laws. Do not use it to bypass access controls or scrape at disruptive rates.

# Features
- Fetch videos + metadata
- Download videos
- Fetch Pornstars
- Fetch Channels
- Fetch Playlists
- Search for videos
- Asynchronous
- Built-in caching
- Easy interface
- Great type hinting

#### Networking Features
- HTTP 2.0 / HTTP 3.0
- Browser impersonation
- Custom JA3
- All proxy types
- Proxy authentication
- Speed Limit
- DNS over HTTPS
- And even more...
- All of this is configurable and can be adjusted as you like!

# Supported Platforms
This API has been tested and confirmed working on:

- Windows 11 (x64) 
- macOS Sequoia (x86_64)
- Linux (Arch) (x86_64)
- Android 16 (aarch64)

# Quickstart

> [!NOTE]
> Full Documentation: [here](https://github.com/EchterAlsFake/API_Docs/blob/master/Porn_APIs/redtube_api.md)


```python
import asyncio
from redtube_api import Client

async def main():
    # Initialize an async client
    client = Client()

    # Fetch and download a video
    video = await client.get_video('https://...')
    print(f"Downloading: {video.title}")
    await video.download(quality="best", path="my-video.mp4") # See docs for more options

  
if __name__ == "__main__":
    asyncio.run(main())
```

# License
RedTube API uses LGPLv3. See the `LICENSE` file.

# Donations
- https://paypal.me/EchterAlsFake

# Contributing
Feel free to contribute to this project by submitting
feature requests, issues, bugs, or whatever.
