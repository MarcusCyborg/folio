import scrapy
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from markdownify import markdownify as md


class WikipediaSpider(scrapy.Spider):
    name = "wiki_spider"
    allowed_domains = ["en.wikipedia.org"]
    start_urls = [
        "https://en.wikipedia.org/wiki/Artificial_intelligence",
        "https://en.wikipedia.org/wiki/Deep_learning",
        "https://en.wikipedia.org/wiki/Machine_learning",
        "https://en.wikipedia.org/wiki/Natural_language_processing",
        "https://en.wikipedia.org/wiki/Computer_vision",
        "https://en.wikipedia.org/wiki/Reinforcement_learning",
        "https://en.wikipedia.org/wiki/Neural_network_(machine_learning)",
        "https://en.wikipedia.org/wiki/Large_language_model",
    ]
    custom_settings = {
        'DEPTH_LIMIT': 4,
        'CLOSESPIDER_ITEMCOUNT': 50000,
        'JOBDIR': 'crawls/wiki50k',
    }

    def __init__(self, *args, **kwargs):
        super(WikipediaSpider, self).__init__(*args, **kwargs)
        self.scraped_count = 0

    def start_requests(self):
        for url in self.start_urls:
            yield scrapy.Request(url, callback=self.parse, dont_filter=False)

    def parse(self, response):
        title_element = response.css("span.mw-page-title-main::text").get()
        if not title_element:
            title_element = response.css("h1#firstHeading *::text").get()
        title = title_element.strip() if title_element else "Unknown title"

        content_html = response.css("div.mw-parser-output").get()
        if content_html:
            soup = BeautifulSoup(content_html, 'html.parser')

            for ref in soup.find_all('sup', class_='reference'):
                ref.decompose()

            unwanted_sections = ['References', 'See_also', 'External_links', 'Further_reading']
            for section_id in unwanted_sections:
                heading_span = soup.find(id=section_id)
                if heading_span and heading_span.parent.name in ['h2', 'h3']:
                    h2_tag = heading_span.parent
                    for sibling in h2_tag.find_next_siblings():
                        sibling.decompose()
                    h2_tag.decompose()

            for box in soup.find_all(['div', 'table'], class_=['navbox', 'reflist', 'metadata', 'mw-empty-elt']):
                box.decompose()

            full_text = md(str(soup), heading_style="ATX", strip=["a", "img"]).strip()
        else:
            full_text = ""

        if full_text and len(full_text) > 100:
            self.scraped_count += 1
            if self.scraped_count % 500 == 0:
                self.logger.info(f"[PROGRESS] Da crawl {self.scraped_count} bai")
            yield {
                'id': self.scraped_count,
                'title': title,
                'url': response.url,
                'text': full_text
            }

        all_links = response.css("div.mw-parser-output a::attr(href)").getall()
        for link in all_links:
            if link.startswith("/wiki/") and not any(x in link for x in [":", "#", "Main_Page"]):
                yield scrapy.Request(url=urljoin(response.url, link), callback=self.parse)
