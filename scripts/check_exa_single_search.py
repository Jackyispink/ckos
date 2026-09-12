"""One explicitly authorized search through the production adapter; no retries."""
import asyncio
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / '.env')
from app.industry_research.search.exa import ExaSearchProvider
from app.industry_research.search.base import SearchRequest


async def main():
    started = time.monotonic()
    async def response_status(response):
        print('http_status', response.status_code, flush=True)
    async with httpx.AsyncClient(timeout=httpx.Timeout(35, connect=10),
                                 event_hooks={'response': [response_status]}) as client:
        provider = ExaSearchProvider(client=client)
        try:
            results = await provider.search(SearchRequest(
                query='工业机器人 精密减速器 RV 谐波 定义 区别', limit=1,
                summary_query='提取工业机器人精密减速器的定义以及RV与谐波减速器的区别。'))
            print('result_count', len(results))
            print('text_lengths', [len(result.text) for result in results])
        except Exception as exc:
            # Adapter errors are explicitly credential-free; never print request objects.
            from app.industry_research.search.base import SearchProviderError
            print('error_type', type(exc).__name__)
            if isinstance(exc, SearchProviderError):
                print('safe_error', str(exc))
    print('elapsed_seconds', round(time.monotonic() - started, 2))


if __name__ == '__main__':
    asyncio.run(main())
