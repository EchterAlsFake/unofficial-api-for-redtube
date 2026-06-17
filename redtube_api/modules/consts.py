from bs4 import BeautifulSoup

try:
    import lxml
    parser = "lxml" # Faster speeds, but more dependencies

except (ModuleNotFoundError, ImportError):
    parser = "html.parser" # Fallback to classic HTML parser (will work fine)


HEADERS = {
    'Accept': '*/*',
    'Accept-Language': 'en,en-US',
    'Connection': 'keep-alive',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/114.0',
    'Referer': 'https://www.redtube.com/',
    'Origin': 'https://www.redtube.com',
}

COOKIES = {
    'accessAgeDisclaimerPH': '1',
    'accessAgeDisclaimerUK': '1',
    'accessRT': '1',
    'age_verified': '1',
    'cookieBannerState': '1',
    'platform': 'pc'
}


def extractor_html(html_content: str) -> list:
    video_urls = []
    soup = BeautifulSoup(html_content, parser)
    stuff = soup.find("ul", class_="videos_grid")
    videos = stuff.find_all("a", class_="video_link tm_video_link js_wrap_trigger_login js_mpop js-pop")

    for video in videos:
        link = video.get("href")
        video_urls.append(f"https://www.redtube.com{link}")

    return video_urls

