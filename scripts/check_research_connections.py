"""Read-only, credential-free HTTP probes. Never submits a search request."""
import asyncio
import os
import inspect
from urllib.parse import urlsplit
from dotenv import load_dotenv
from pathlib import Path
import httpx

load_dotenv(Path(__file__).resolve().parents[1] / '.env')


async def main():
    url = os.getenv('EXA_SEARCH_URL') or 'https://api.exa.ai/search'
    parts = urlsplit(url)
    print('exa_endpoint', parts.scheme, parts.hostname, parts.path)
    print('key_present', bool(os.getenv('EXA_API_KEY', '').strip()))
    print('proxy_variables', [k for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY') if os.getenv(k)])
    for trust in (True, False):
        try:
            async with httpx.AsyncClient(trust_env=trust, timeout=12) as client:
                # No key, no query, no billable search; uses the app's async transport.
                r = await client.get(url)
                print('async_https', trust, r.status_code)
                r = await client.post(url, json={'query': 'industrial reducer', 'numResults': 1})
                print('unauthenticated_post', trust, r.status_code)
        except Exception as exc:
            chain = []
            while exc:
                chain.append((type(exc).__name__, getattr(exc, 'errno', None), getattr(exc, 'winerror', None)))
                exc = exc.__cause__
            print('async_https', trust, chain)
    import akshare as ak
    print('akshare_version', ak.__version__)
    for name in ('macro_china_gdp', 'macro_china_ppi', 'macro_china_pmi'):
        function = getattr(ak, name, None)
        print('akshare_interface', name, str(inspect.signature(function)) if function else 'MISSING')
        if function:
            try:
                frame = await asyncio.wait_for(asyncio.to_thread(function), 25)
                print('akshare_fetch', name, len(frame), list(frame.columns),
                      'first_period', str(frame.iloc[0, 0]), 'last_period', str(frame.iloc[-1, 0]))
            except Exception as exc:
                print('akshare_fetch', name, type(exc).__name__)


if __name__ == '__main__':
    asyncio.run(main())
