# Atlas Executive Insights - Quick Reference

## 🚀 Start Development

```powershell
# Terminal 1 - Backend
cd backend
venv\Scripts\activate
python main.py

# Terminal 2 - Frontend  
cd frontend
npm run dev
```

**Access:**
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

---

## 📁 Project Structure

```
atlas-executive-insights/
├── backend/                    # Python FastAPI backend
│   ├── main.py                # Entry point, API routes
│   ├── requirements.txt       # Python dependencies
│   ├── .env                   # Config (create from .env.example)
│   ├── config/
│   │   └── settings.py        # Environment configuration
│   ├── models/
│   │   └── kpi.py            # Data models (KPI, Insight, Forecast)
│   └── services/
│       ├── data_fetcher.py   # Database queries
│       ├── forecasting.py    # ML forecasting (Prophet)
│       ├── insights_engine.py # Azure OpenAI integration
│       └── metrics.py        # KPI calculations
│
├── frontend/                   # React web app
│   ├── src/
│   │   ├── App.jsx           # Main app component
│   │   ├── services/
│   │   │   └── api.js        # Backend API client
│   │   └── components/       # UI components
│   │       ├── Header.jsx
│   │       ├── KPICards.jsx
│   │       ├── DescriptiveAnalytics.jsx
│   │       ├── AIInsights.jsx
│   │       └── PredictiveAnalytics.jsx
│   ├── package.json
│   └── vite.config.js
│
├── docs/
│   └── POC_PLAN.md           # Week 1 development plan
├── README.md                  # Project overview
└── SETUP.md                   # Detailed setup guide
```

---

## 🔧 Common Commands

### Backend
```powershell
# Install dependencies
pip install -r requirements.txt

# Run server
python main.py

# Run with auto-reload
uvicorn main:app --reload

# Test database connection
python -c "from services.data_fetcher import DataFetcher; df = DataFetcher(); df.get_connection()"

# Test API endpoint
curl http://localhost:8000/api/kpis
```

### Frontend
```powershell
# Install dependencies
npm install

# Run dev server
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

---

## 📊 Key Files to Customize

### 1. Database Queries
**File:** `backend/services/data_fetcher.py`

Replace mock queries with your actual database queries:
```python
async def fetch_kpi_data(self, start_date, end_date):
    query = """
    SELECT 
        metric_name,
        metric_value,
        target_value,
        previous_period_value
    FROM your_kpi_table  -- ← Change this
    WHERE metric_date BETWEEN ? AND ?
    """
```

### 2. Azure OpenAI Prompts
**File:** `backend/services/insights_engine.py`

Customize insight generation prompts:
```python
prompt = f"""
You are an expert business intelligence analyst...
[Customize this prompt for your domain]
"""
```

### 3. UI Styling
**File:** `frontend/tailwind.config.js`

Change colors and branding:
```javascript
theme: {
  extend: {
    colors: {
      primary: '#4F46E5',  // ← Your brand color
      secondary: '#8B5CF6',
    }
  }
}
```

### 4. KPI Configuration
**File:** `backend/services/metrics.py`

Add/modify KPIs:
```python
name_map = {
    'revenue': 'Total Revenue',
    'your_kpi': 'Your KPI Name',  // ← Add yours
}
```

---

## 🐛 Troubleshooting

### "Module not found" errors

**Backend:**
```powershell
cd backend
pip install -r requirements.txt
```

**Frontend:**
```powershell
cd frontend
rm -rf node_modules
npm install
```

### "Can't connect to database"

1. Check `.env` file exists and has correct credentials
2. Test from Power BI first
3. Check firewall rules
4. Verify ODBC driver is installed

### "Prophet installation fails"

Prophet requires C++ build tools. Options:
1. Install Visual Studio Build Tools
2. Use conda: `conda install -c conda-forge prophet`
3. Tool will fall back to linear regression automatically

### Port already in use

**Backend (port 8000):**
```powershell
# Find and kill process
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

**Frontend (port 3000):**
Edit `frontend/vite.config.js`:
```javascript
server: {
  port: 3001,  // Use different port
}
```

---

## 🎯 API Endpoints Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health check |
| `/api/kpis` | GET | Get all KPI cards |
| `/api/charts/{chart_type}` | GET | Get chart data |
| `/api/insights` | GET | Get AI insights |
| `/api/forecast` | GET | Get metric forecast |
| `/api/recommendations` | GET | Get AI recommendations |

**Query Parameters:**
- `start_date` - Start date (YYYY-MM-DD)
- `end_date` - End date (YYYY-MM-DD)
- `metric` - Metric name for forecasting
- `periods` - Number of days to forecast

**Example:**
```bash
curl "http://localhost:8000/api/kpis?start_date=2024-05-01&end_date=2024-05-31"
```

---

## 📚 Documentation Links

- **FastAPI**: https://fastapi.tiangolo.com/
- **Prophet**: https://facebook.github.io/prophet/docs/quick_start.html
- **Azure OpenAI**: https://learn.microsoft.com/en-us/azure/ai-services/openai/
- **React**: https://react.dev/
- **Vite**: https://vitejs.dev/
- **Chart.js**: https://www.chartjs.org/
- **Tailwind CSS**: https://tailwindcss.com/

---

## 🔐 Environment Variables

### Backend (.env)
```env
# Database
DB_SERVER=your-server.database.windows.net
DB_NAME=your_database
DB_USER=your_username
DB_PASSWORD=your_password

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_DEPLOYMENT=gpt-4

# App Settings
ENVIRONMENT=development
DEBUG=True
```

---

## ✅ Pre-Deployment Checklist

- [ ] Replace all mock data with real queries
- [ ] Test all API endpoints
- [ ] Verify forecasting accuracy
- [ ] Test AI insights quality
- [ ] Implement error handling
- [ ] Add loading states
- [ ] Test responsive design
- [ ] Review security (no exposed secrets)
- [ ] Set up authentication
- [ ] Configure production environment variables
- [ ] Test with real users

---

## 🎨 Design System

### Colors
- Primary: `#4F46E5` (Indigo)
- Secondary: `#8B5CF6` (Purple)
- Success: `#10B981` (Green)
- Warning: `#F59E0B` (Amber)
- Danger: `#EF4444` (Red)

### Typography
- Font: Inter (system fallback)
- Headers: 600-700 weight
- Body: 400-500 weight

### Spacing
- Card padding: 1.5rem (24px)
- Section gap: 2rem (32px)
- Grid gap: 1.5rem (24px)

---

## 📞 Support

For questions or issues:
1. Check [SETUP.md](SETUP.md) for detailed setup
2. Review [POC_PLAN.md](docs/POC_PLAN.md) for development roadmap
3. Check API docs at http://localhost:8000/docs
4. Review browser console for frontend errors
5. Check backend terminal for API errors

---

**Ready to start? Run the commands at the top! 🚀**
