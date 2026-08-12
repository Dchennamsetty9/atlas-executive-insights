# Atlas Executive Insights - Setup Guide

## 🚀 Quick Start

### 1. Backend Setup

```powershell
# Navigate to backend directory
cd backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
copy .env.example .env
# Edit .env with your database and Azure OpenAI credentials

# Run the backend server
python main.py
```

Backend will be available at: http://localhost:8000

API documentation: http://localhost:8000/docs

### 2. Frontend Setup

```powershell
# Open a new terminal
cd frontend

# Install dependencies
npm install

# Run development server
npm run dev
```

Frontend will be available at: http://localhost:3000

---

## 📝 Configuration

### Backend Configuration (.env)

1. **Database Connection**
   - Update `DB_SERVER`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
   - These should match your Power BI data source

2. **Azure OpenAI**
   - Get your Azure OpenAI endpoint and API key from Azure Portal
   - Update `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_API_KEY`
   - Set deployment name in `AZURE_OPENAI_DEPLOYMENT`

3. **Forecasting Settings**
   - Adjust `FORECAST_DEFAULT_PERIODS` (default: 90 days)
   - Adjust `FORECAST_CONFIDENCE_INTERVAL` (default: 0.95)

### Frontend Configuration

No additional configuration needed for development. The frontend proxies API requests to the backend automatically.

---

## 🔧 Customization Guide

### Adding New KPIs

1. **Update Database Query** in `backend/services/data_fetcher.py`:
   ```python
   async def fetch_kpi_data(self, start_date, end_date):
       query = """
       SELECT 
           metric_name,
           metric_value,
           -- Add your KPI fields here
       FROM your_kpi_table
       """
   ```

2. **Update Metrics Calculator** in `backend/services/metrics.py`:
   - Add metric name to `_format_metric_name()`
   - Add formatting logic to `_format_value()`
   - Add icon mapping to `_get_icon()`

3. **Frontend automatically updates** - KPI cards are dynamic!

### Adding New Charts

1. **Add Query** in `backend/services/data_fetcher.py`:
   ```python
   query_map = {
       "your_chart_type": """
           SELECT columns FROM table
           WHERE conditions
       """
   }
   ```

2. **Add Chart Preparation** in `backend/services/metrics.py`:
   ```python
   def _prepare_your_chart(self, raw_data):
       return ChartData(...)
   ```

3. **Add Component** in `frontend/src/components/DescriptiveAnalytics.jsx`

### Customizing AI Insights

Edit prompts in `backend/services/insights_engine.py`:
- `generate_insights()` - for alerts and observations
- `generate_recommendations()` - for actionable recommendations

---

## 🎨 UI Customization

### Colors
Edit `frontend/tailwind.config.js`:
```javascript
theme: {
  extend: {
    colors: {
      primary: '#YOUR_COLOR',
      secondary: '#YOUR_COLOR',
    }
  }
}
```

### Components
All UI components are in `frontend/src/components/`:
- `Header.jsx` - Top navigation
- `KPICards.jsx` - Metric cards
- `DescriptiveAnalytics.jsx` - Charts section
- `AIInsights.jsx` - AI insights panel
- `PredictiveAnalytics.jsx` - Forecasting chart

---

## 🗃️ Database Connection

### Connecting to Your Power BI Data Source

The tool should connect to the **same database that Power BI uses**:

1. **Find your Power BI data source**:
   - Open Power BI Desktop
   - Go to Transform Data → Data source settings
   - Note the server and database name

2. **Update backend/.env**:
   ```
   DB_SERVER=your-server.database.windows.net
   DB_NAME=your_database
   DB_USER=your_username
   DB_PASSWORD=your_password
   ```

3. **Test connection**:
   ```powershell
   cd backend
   python -c "from services.data_fetcher import DataFetcher; df = DataFetcher(); print('Connected!' if df.get_connection() else 'Failed')"
   ```

---

## 🤖 Azure OpenAI Setup

### Getting Your Credentials

1. **Azure Portal** → **Azure OpenAI Service**
2. Navigate to your resource
3. Go to **Keys and Endpoint**
4. Copy:
   - Endpoint URL
   - One of the keys
   - Deployment name (usually `gpt-4` or `gpt-35-turbo`)

### Update .env

```
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key-here
AZURE_OPENAI_DEPLOYMENT=gpt-4
```

---

## 📊 Forecasting Models

### Current Implementation

The tool uses **Prophet** (Facebook's time series forecasting library) with fallback to linear regression.

### Customizing Forecasting

Edit `backend/services/forecasting.py`:

```python
def _forecast_with_prophet(self, metric, historical_data, periods):
    model = Prophet(
        daily_seasonality=True,
        weekly_seasonality=True,
        yearly_seasonality=True,
        # Add custom parameters
    )
```

### Improving Accuracy

1. **More historical data** - Provide at least 6 months
2. **Feature engineering** - Add external factors (holidays, campaigns)
3. **Model tuning** - Adjust seasonality and trend parameters
4. **Cross-validation** - Use Prophet's built-in CV

---

## 🐛 Troubleshooting

### Backend Issues

**"pyodbc driver not found"**
- Install ODBC Driver 18 for SQL Server
- Download: https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server

**"Connection failed"**
- Check firewall rules
- Verify credentials in .env
- Test connection from Power BI first

**"Prophet import error"**
- Prophet requires C++ build tools
- Alternative: Tool falls back to linear regression automatically

### Frontend Issues

**"Module not found"**
```powershell
cd frontend
rm -rf node_modules package-lock.json
npm install
```

**"Port 3000 already in use"**
- Edit `frontend/vite.config.js` to use a different port
- Or stop the process using port 3000

---

## 📦 Deployment

### Production Deployment

1. **Backend**:
   ```powershell
   cd backend
   pip install gunicorn
   gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker
   ```

2. **Frontend**:
   ```powershell
   cd frontend
   npm run build
   # Deploy dist/ folder to web server
   ```

### Docker Deployment (Optional)

Coming soon - Docker Compose configuration for easy deployment.

---

## 🔐 Security Notes

- **Never commit .env files** - They contain sensitive credentials
- **Use environment variables** in production
- **Implement authentication** before deploying publicly
- **Restrict database permissions** to read-only if possible
- **Rotate API keys** regularly

---

## 📚 Next Steps

1. ✅ Set up backend with your database
2. ✅ Configure Azure OpenAI
3. ✅ Customize KPIs to match your metrics
4. ✅ Add your company branding
5. ✅ Test forecasting accuracy
6. ✅ Deploy to production

---

## 🆘 Getting Help

For issues or questions:
1. Check troubleshooting section above
2. Review backend logs in terminal
3. Check browser console for frontend errors
4. Verify API is responding: http://localhost:8000/docs

---

**Built for the GAIM Team**
