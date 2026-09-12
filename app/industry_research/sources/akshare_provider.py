import asyncio
import json
from datetime import datetime, timezone

from .base import DataRequirement, DataSourceError, StructuredEvidence


# Explicit whitelist: model/user text can never select an arbitrary Python callable.
DATASETS = {
    'china_gdp': {'function': 'macro_china_gdp', 'title': '中国国内生产总值', 'url': 'http://data.eastmoney.com/cjsj/gdp.html'},
    'china_ppi': {'function': 'macro_china_ppi', 'title': '中国工业品出厂价格指数（PPI）', 'url': 'http://data.eastmoney.com/cjsj/ppi.html'},
    'china_pmi': {'function': 'macro_china_pmi', 'title': '中国采购经理人指数（PMI）', 'url': 'http://data.eastmoney.com/cjsj/pmi.html'},
    'china_trade': {'function': 'macro_china_hgjck', 'title': '中国海关进出口数据', 'url': 'https://data.eastmoney.com/cjsj/hgjck.html'},
    'company_financials': {'function': 'stock_financial_analysis_indicator', 'title': '上市公司财务分析指标', 'url': 'https://money.finance.sina.com.cn/', 'required': {'symbol', 'start_year'}},
}


class AkshareProvider:
    name = 'akshare'

    @staticmethod
    def configured():
        try:
            import akshare  # noqa: F401
            return True
        except ImportError:
            return False

    async def fetch(self, requirement: DataRequirement) -> StructuredEvidence:
        spec = DATASETS.get(requirement.key)
        if not spec:
            raise DataSourceError(f'AKShare白名单中没有数据集：{requirement.key}')
        missing = spec.get('required', set()) - requirement.params.keys()
        if missing:
            raise DataSourceError(f'{spec["title"]}缺少参数：{"、".join(sorted(missing))}')
        try:
            frame = await asyncio.wait_for(asyncio.to_thread(self._call, spec, requirement.params), timeout=35)
        except TimeoutError:
            raise DataSourceError(f'AKShare获取“{spec["title"]}”超时。') from None
        except DataSourceError:
            raise
        except Exception:
            raise DataSourceError(f'AKShare暂时无法获取“{spec["title"]}”。') from None
        if frame is None or frame.empty:
            raise DataSourceError(f'AKShare“{spec["title"]}”没有返回数据。')
        compact = frame.tail(20).copy()
        compact = compact.where(compact.notna(), None)
        records = json.loads(compact.to_json(orient='records', force_ascii=False, date_format='iso'))
        columns = [str(x) for x in compact.columns]
        text = f'数据集：{spec["title"]}\n字段：{"、".join(columns)}\n最近记录：\n{json.dumps(records, ensure_ascii=False)}'
        return StructuredEvidence(
            title=spec['title'], text=text[:9000], source_url=spec['url'], provider=self.name,
            dataset=requirement.key, metadata={'function': spec['function'], 'rows_returned': len(frame),
                'rows_in_evidence': len(compact), 'retrieved_at': datetime.now(timezone.utc).isoformat()},
        )

    @staticmethod
    def _call(spec, params):
        import akshare as ak
        function = getattr(ak, spec['function'], None)
        if not callable(function):
            raise DataSourceError(f'当前AKShare版本不包含接口：{spec["function"]}')
        return function(**params)
