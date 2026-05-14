"""
Forecasting service using Prophet and scikit-learn

Version: 0.4.0 - ARR Forecast Compatible
Based on: ARR Forecast.pbip Prophet methodology

Configuration matches ARR Forecast dashboard:
- Daily/weekly/yearly seasonality enabled
- 80% confidence interval (best case / worst case bounds)
- Weekly aggregation with ISO week numbering
- Seasonality features: summer/winter/week1 flags
- 3 scenarios: best_case, most_likely, worst_case
"""

from typing import Dict, List
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Try to import Prophet (optional dependency)
try:
    from prophet import Prophet
    PROPHET_AVAILABLE = True
except ImportError:
    PROPHET_AVAILABLE = False
    print("⚠️  Prophet not installed - will use alternative models")

from sklearn.linear_model import LinearRegression

from models.kpi import Forecast, ForecastPoint
from config.settings import settings


class ForecastingService:
    """Advanced multi-model forecasting service"""
    
    AVAILABLE_MODELS = {
        'prophet': 'Prophet (Facebook AI) - Best for seasonal data',
        'arima': 'ARIMA - Statistical time series model',
        'exponential': 'Exponential Smoothing - Trend + seasonality',
        'ensemble': 'Ensemble - Combines multiple models (recommended)',
        'linear': 'Linear Regression - Simple baseline'
    }
    
    def __init__(self):
        self.models = {}
        self.model_accuracy = {}
        
    def forecast(
        self, 
        metric: str, 
        historical_data: pd.DataFrame, 
        periods: int = None,
        model: str = 'ensemble'
    ) -> Forecast:
        """Generate forecast using specified model
        
        Args:
            metric: Name of the metric to forecast
            historical_data: DataFrame with columns [ds, y] (date, value)
            periods: Number of days to forecast
            model: Forecasting model ('prophet', 'arima', 'exponential', 'ensemble', 'linear')
            
        Returns:
            Forecast object with historical and predicted values + accuracy metrics
        """
        
        if periods is None:
            periods = settings.forecast_default_periods
        
        # Route to appropriate model
        if model == 'ensemble':
            return self._forecast_ensemble(metric, historical_data, periods)
        elif model == 'prophet' and PROPHET_AVAILABLE:
            return self._forecast_with_prophet(metric, historical_data, periods)
        elif model == 'arima':
            return self._forecast_with_arima(metric, historical_data, periods)
        elif model == 'exponential':
            return self._forecast_with_exponential_smoothing(metric, historical_data, periods)
        elif model == 'linear':
            return self._forecast_with_linear_regression(metric, historical_data, periods)
        else:
            print(f"Model '{model}' not available, using ensemble")
            return self._forecast_ensemble(metric, historical_data, periods)
    
    def get_model_comparison(self, metric: str, historical_data: pd.DataFrame) -> Dict:
        """Compare accuracy of all available models
        
        Returns: Dict with model names and their accuracy metrics
        """
        comparison = {}
        test_size = min(30, len(historical_data) // 5)  # Use last 20% or 30 days for testing
        train_data = historical_data[:-test_size]
        test_data = historical_data[-test_size:]
        
        models_to_test = ['prophet', 'arima', 'exponential', 'linear']
        
        for model_name in models_to_test:
            try:
                # Generate forecast on training data
                forecast_result = self.forecast(metric, train_data, periods=test_size, model=model_name)
                
                # Extract predictions for test period
                predictions = forecast_result.forecast[-test_size:]
                pred_values = [p.most_likely for p in predictions]
                actual_values = test_data['y'].values
                
                # Calculate accuracy metrics
                mape = self._calculate_mape(actual_values, pred_values)
                rmse = np.sqrt(mean_squared_error(actual_values, pred_values))
                mae = mean_absolute_error(actual_values, pred_values)
                
                comparison[model_name] = {
                    'mape': round(mape, 2),
                    'rmse': round(rmse, 2),
                    'mae': round(mae, 2),
                    'accuracy': round(100 - mape, 2)
                }
            except Exception as e:
                print(f"Model {model_name} comparison failed: {e}")
                comparison[model_name] = {'error': str(e)}
        
        return comparison
    
    def _forecast_with_prophet(
        self, 
        metric: str, 
        historical_data: pd.DataFrame, 
        periods: int
    ) -> Forecast:
        """
        Forecast using Facebook Prophet (ARR Forecast methodology)
        
        Configuration matches ARR Forecast.pbip:
        - interval_width: 0.80 (80% confidence interval)
        - Seasonality: daily, weekly, yearly all enabled
        - Output: best_case (yhat_upper), most_likely (yhat), worst_case (yhat_lower)
        
        Requires historical_data with columns: ds (datetime), y (value)
        """
        
        # Add seasonality features matching ARR Forecast
        historical_data = historical_data.copy()
        historical_data['summer'] = historical_data['ds'].dt.month.isin([6, 7, 8]).astype(int)
        historical_data['winter'] = historical_data['ds'].dt.month.isin([12, 1, 2]).astype(int)
        historical_data['isweek1'] = (historical_data['ds'].dt.day <= 7).astype(int)
        
        # Initialize Prophet with ARR Forecast configuration
        model = Prophet(
            interval_width=0.80,              # 80% confidence interval (matches ARR Forecast)
            daily_seasonality=True,           # Capture daily patterns
            weekly_seasonality=True,          # Capture weekly patterns (Mon-Sun)
            yearly_seasonality=True           # Capture annual seasonality
        )
        
        # Add custom seasonality regressors
        model.add_regressor('summer')
        model.add_regressor('winter')
        model.add_regressor('isweek1')
        
        # Train model
        model.fit(historical_data[['ds', 'y', 'summer', 'winter', 'isweek1']])
        
        # Make future dataframe
        future = model.make_future_dataframe(periods=periods)
        
        # Add seasonality features to future dates
        future['summer'] = future['ds'].dt.month.isin([6, 7, 8]).astype(int)
        future['winter'] = future['ds'].dt.month.isin([12, 1, 2]).astype(int)
        future['isweek1'] = (future['ds'].dt.day <= 7).astype(int)
        
        # Generate predictions
        forecast_df = model.predict(future)
        
        # Split historical and forecast
        hist_size = len(historical_data)
        historical_points = [
            ForecastPoint(
                date=row['ds'].strftime('%Y-%m-%d'),
                value=float(row['y'])
            )
            for _, row in historical_data.iterrows()
        ]
        
        # Extract 3 scenarios matching ARR Forecast
        forecast_points = [
            ForecastPoint(
                date=row['ds'].strftime('%Y-%m-%d'),
                value=float(row['yhat']),                    # most_likely
                lower_bound=float(row['yhat_lower']),        # worst_case
                upper_bound=float(row['yhat_upper'])         # best_case
            )
            for _, row in forecast_df[hist_size:].iterrows()
        ]
        
        # Calculate accuracy on historical data (MAPE-based)
        historical_predictions = forecast_df[:hist_size]['yhat'].values
        historical_actuals = historical_data['y'].values
        mape = np.mean(np.abs((historical_actuals - historical_predictions) / (historical_actuals + 1e-10))) * 100
        accuracy = max(0, 100 - mape) / 100  # Convert MAPE to accuracy score
        
        return Forecast(
            metric=metric,
            historical=historical_points,
            forecast=forecast_points,
            accuracy=float(accuracy),
            confidence_interval=settings.forecast_confidence_interval
        )
    
    def _forecast_with_linear_regression(
        self, 
        metric: str, 
        historical_data: pd.DataFrame, 
        periods: int
    ) -> Forecast:
        """
        Simple linear regression forecast (fallback method)
        """
        
        # Prepare data
        historical_data = historical_data.copy()
        historical_data['ds'] = pd.to_datetime(historical_data['ds'])
        historical_data['x'] = (historical_data['ds'] - historical_data['ds'].min()).dt.days
        
        X = historical_data[['x']].values
        y = historical_data['y'].values
        
        # Train model
        model = LinearRegression()
        model.fit(X, y)
        
        # Historical points
        historical_points = [
            ForecastPoint(
                date=row['ds'].strftime('%Y-%m-%d'),
                value=float(row['y'])
            )
            for _, row in historical_data.iterrows()
        ]
        
        # Forecast future points
        last_date = historical_data['ds'].max()
        future_dates = [last_date + timedelta(days=i+1) for i in range(periods)]
        future_x = np.array([[(last_date + timedelta(days=i+1) - historical_data['ds'].min()).days] 
                             for i in range(periods)])
        
        predictions = model.predict(future_x)
        
        # Calculate confidence interval (simple standard error approach)
        residuals = y - model.predict(X)
        std_error = np.std(residuals)
        z_score = 1.96  # 95% confidence
        
        forecast_points = [
            ForecastPoint(
                date=date.strftime('%Y-%m-%d'),
                value=float(pred),
                lower_bound=float(pred - z_score * std_error),
                upper_bound=float(pred + z_score * std_error)
            )
            for date, pred in zip(future_dates, predictions)
        ]
        
        # Calculate R² score as accuracy metric
        accuracy = model.score(X, y)
        
        return Forecast(
            metric=metric,
            historical=historical_points,
            forecast=forecast_points,
            accuracy=float(accuracy),
            confidence_interval=0.95
        )
    
    async def get_all_forecasts(self, periods: int = 90) -> Dict[str, Forecast]:
        """
        Get forecasts for all key metrics including ARR
        """
        from services.data_fetcher import DataFetcher
        
        data_fetcher = DataFetcher()
        forecasts = {}
        
        # Key metrics to forecast
        metrics = ['arr', 'won_pipeline', 'active_pipeline', 'created_pipeline']
        
        for metric in metrics:
            try:
                historical_data = await data_fetcher.fetch_historical_data(metric)
                if not historical_data.empty:
                    forecast = self.forecast(metric, historical_data, periods)
                    forecasts[metric] = forecast
            except Exception as e:
                print(f"Error forecasting {metric}: {e}")
                continue
        
        return forecasts
    
    # Import additional forecasting methods
    def _forecast_with_arima(self, metric: str, historical_data: pd.DataFrame, periods: int) -> Forecast:
        """ARIMA forecast - delegates to forecasting_models"""
        from services.forecasting_models import forecast_with_arima
        return forecast_with_arima(metric, historical_data, periods)
    
    def _forecast_with_exponential_smoothing(self, metric: str, historical_data: pd.DataFrame, periods: int) -> Forecast:
        """Exponential Smoothing forecast - delegates to forecasting_models"""
        from services.forecasting_models import forecast_with_exponential_smoothing
        return forecast_with_exponential_smoothing(metric, historical_data, periods)
    
    def _forecast_ensemble(self, metric: str, historical_data: pd.DataFrame, periods: int) -> Forecast:
        """Ensemble forecast combining multiple models"""
        from services.forecasting_models import forecast_ensemble
        
        # Generate forecasts from all available models
        prophet_forecast = None
        arima_forecast = None
        exp_forecast = None
        
        try:
            if PROPHET_AVAILABLE:
                prophet_forecast = self._forecast_with_prophet(metric, historical_data, periods)
        except Exception as e:
            print(f"Prophet failed in ensemble: {e}")
        
        try:
            arima_forecast = self._forecast_with_arima(metric, historical_data, periods)
        except Exception as e:
            print(f"ARIMA failed in ensemble: {e}")
        
        try:
            exp_forecast = self._forecast_with_exponential_smoothing(metric, historical_data, periods)
        except Exception as e:
            print(f"Exponential Smoothing failed in ensemble: {e}")
        
        # Combine using weighted ensemble
        return forecast_ensemble(metric, historical_data, periods, prophet_forecast, arima_forecast, exp_forecast)
    
    def _calculate_mape(self, actual: np.ndarray, predicted: np.ndarray) -> float:
        """Calculate Mean Absolute Percentage Error"""
        from services.forecasting_models import calculate_mape
        return calculate_mape(actual, predicted)
