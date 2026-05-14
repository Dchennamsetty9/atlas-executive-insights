# Atlas Executive Insights

AI-powered executive analytics dashboard combining Power BI KPIs with forecasting and automated insights.

## 🎯 Overview

This tool provides:
- **Real-time KPI Monitoring**: Connect to your Power BI data sources
- **Descriptive Analytics**: Interactive charts showing trends and patterns
- **Predictive Analytics**: ML-based forecasting using Prophet/scikit-learn
- **AI Insights**: Azure OpenAI-generated recommendations and alerts

## 🏗️ Architecture

```
atlas-executive-insights/
├── backend/              # FastAPI Python backend
├── frontend/             # React web application
├── forecasting/          # ML models and forecasting logic
├── shared/               # Shared configs and utilities
└── docs/                 # Documentation
```

## 🚀 Quick Start

### Prerequisites
- Python 3.9+
- Node.js 18+
- Azure OpenAI API access
- Database connection (same as Power BI)

### Backend Setup
```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

### Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

## 📊 Features Roadmap

### Week 1 POC
- [x] Project structure
- [ ] Backend API endpoints
- [ ] Database connection
- [ ] Basic forecasting
- [ ] Azure OpenAI integration
- [ ] Frontend UI components
- [ ] KPI cards
- [ ] Charts integration

### Future Enhancements
- [ ] Real-time data refresh
- [ ] Custom alert rules
- [ ] Export to PDF/PowerPoint
- [ ] Mobile responsive design
- [ ] User authentication

## 📝 License

Internal use - GAIM Team

## 🤝 Contributing

Contact: GAIM Team
