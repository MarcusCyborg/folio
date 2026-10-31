import string 
import re
import nltk
from rake_nltk import Rake
from nltk.corpus import stopwords
from nltk.tag import pos_tag

try:
    nltk.data.find('tokenizers/punkt')
    nltk.data.find('tokenizers/punkt_tab')
    nltk.data.find('corpora/stopwords')
    nltk.data.find('taggers/averaged_perceptron_tagger')
    nltk.data.find('taggers/averaged_perceptron_tagger_eng')
except LookupError:
    nltk.download('punkt')
    nltk.download('punkt_tab')
    nltk.download('stopwords')
    nltk.download('averaged_perceptron_tagger')
    nltk.download('averaged_perceptron_tagger_eng')

class QueryExtraction:
    def __init__(self):
        self.rake = Rake(min_length=1, max_length=3)
        self.stop_words = set(stopwords.words('english'))
        custom_sw = {'want', 'know', 'find', 'tell', 'about', 'detail', 'information', 'what', 'how', 'why', 'who'}
        self.stop_words.update(custom_sw)

    def tokenization(self, raw_query:str)-> list:
        tokens = re.findall(r'[a-z0-9]+', raw_query.lower())
        return tokens

    def extract(self, raw_query: str) -> dict:
        self.rake.extract_keywords_from_text(raw_query)
        rake_keywords = self.rake.get_ranked_phrases()[:3]

        tokens = self.tokenization(raw_query)
        clean_tokens = [
            token for token in tokens
            if token not in self.stop_words and token not in string.punctuation
        ]
        pos_tags = pos_tag(clean_tokens)
        prim_keywords = [
            token for token, tag in pos_tags
            if tag.startswith('NN') or tag.startswith('JJ') or tag.startswith('VB')
        ]
        if not prim_keywords:
            prim_keywords = clean_tokens

        seen = {}
        for kw in rake_keywords + prim_keywords:
            kw_lower = kw.lower()
            if kw_lower not in seen:
                seen[kw_lower] = kw

        combine_search_query = " ".join(seen.keys())
        if not combine_search_query.strip():
            combine_search_query = raw_query

        return {
            'context': raw_query,
            'search_keywords': combine_search_query
        }