from scrapers.models import Promocion
from typing import List


class BaseScraper:
    nombre: str = "Base"
    url_base: str = ""

    def scrape(self) -> List[Promocion]:
        raise NotImplementedError
