export const TABS = ['Overview', 'Multi-Year', 'By Product', 'Monthly', 'Accuracy', 'Model Lab', 'AI Insights', 'Exec Mode'];
export const MODELS = ['ensemble', 'prophet', 'ets', 'mstl_v2', 'dhr_arima', 'lightgbm'];
export const PROD_LINES = ['All', 'UCC', 'ITSG'];
export const FC_TYPES = [{ key: 'rolling', label: '13-Week Quarter' }, { key: 'roy', label: 'Rest of Year' }];

export const MODEL_KEY_META = {
	ensemble: { label: 'Ensemble', color: '#00FF88' },
	prophet: { label: 'Prophet', color: '#f59e0b' },
	ets: { label: 'ETS', color: '#94a3b8' },
	mstl_v2: { label: 'MSTL', color: '#a78bfa' },
	dhr_arima: { label: 'DHR-ARIMA', color: '#fb923c' },
	lightgbm: { label: 'LightGBM', color: '#3b82f6' },
};

export const MODEL_LB_KEY = {
	ensemble: 'Ensemble',
	prophet: 'Prophet',
	ets: 'ETS',
	mstl_v2: 'MSTL_v2',
	dhr_arima: 'DHR_ARIMA',
	lightgbm: 'LightGBM',
};
