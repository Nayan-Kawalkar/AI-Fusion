from django.core.management.base import BaseCommand

from rag.retrieve import retrieve_collection
from rag.store import DOCS_COLLECTION


class Command(BaseCommand):
    help = 'Hybrid-search the documentation KB: search_docs "list comprehension"'

    def add_arguments(self, parser):
        parser.add_argument("query")
        parser.add_argument("-k", type=int, default=5)

    def handle(self, *args, **opts):
        results = retrieve_collection(DOCS_COLLECTION, [opts["query"]], opts["k"])
        if not results:
            self.stdout.write("No documents indexed.")
        for i, r in enumerate(results, 1):
            preview = " ".join(r["text"].split())[:160]
            self.stdout.write(
                f"{i}. score={r['score']:.3f}  {r['title']} p.{r['page']}  [{r['heading']}]\n   {preview}"
            )
