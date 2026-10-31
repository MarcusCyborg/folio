# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface
from itemadapter import ItemAdapter


class WikiBotPipeline:
    def process_item(self, item, spider):
        return item

class DuplicatesPipeline:
    def __init__(self):
        self.seen_urls = set()

    def process_item(self, item, spider):
        url = item.get('url', '')
        if url in self.seen_urls:
            from scrapy.exceptions import DropItem
            raise DropItem(f"Duplicate URL: {url}")
        self.seen_urls.add(url)
        return item
