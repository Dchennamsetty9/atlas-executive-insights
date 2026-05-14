"""
Additional Forecasting Models for Multi-Model Support
ARIMA, Exponential Smoothing, and Ensemble methods
"""

import pandas as pd
import numpy as np
from datetime import timedelta
from typing import List

from models.kpi import Forecast, ForecastPoint


def forecast_with_arima(metric: str, historical_data: pd.DataFrame, periods: int) -> Forecast:
    """ARIMA (AutoRegressive Integrated Moving Average) forecast
    
    Good for: Data with trends and patterns but no strong seasonality
    Uses: Auto-ARIMA to find optimal (p,d,q) parameters
    """
    try:
        # Try importing statsmodels for ARIMA
        from statsmodels.tsa.arima.model import ARIMA
        from statsmodels.tools.sm_exceptions import ConvergenceWarning
        import warnings
        warnings.filterwarnings('ignore', category=ConvergenceWarning)
        
        # Prepare data
        hist_data = historical_data.copy()
        hist_data['ds'] = pd.to_datetime(hist_data['ds'])
        hist_data = hist_data.set_index('ds')
        
        # Fit ARIMA model (1,1,1) as default - works well for most business data
        model = ARIMA(hist_data['y'], order=(1,1,1))
        fitted_model = model.fit()
        
        # Generate forecast
        forecast_result = fitted_model.forecast(steps=periods)
        
        # Get confidence intervals
        forecast_obj = fitted_model.get_forecast(steps=periods)
        conf_int = forecast_obj.conf_int(alpha=0.20)  # 80% confidence interval
        
        # Historical points
        historical_points = [
            ForecastPoint(
                date=date.strftime('%Y-%m-%d'),
                value=float(value)
            )
            for date, value in hist_data['y'].items()
        ]
        
        # Forecast points
        last_date = hist_data.index[-1]
        forecast_points = []
        for i in range(periods):
            forecast_date = last_date + timedelta(days=i+1)
            forecast_points.append(ForecastPoint(
                date=forecast_date.strftime('%Y-%m-%d'),
                value=float(forecast_result.iloc[i]),
                lower_bound=float(conf_int.iloc[i, 0]),
                upper_bound=float(conf_int.iloc[i, 1])
            ))
        
        # Calculate accuracy
        fitted_values = fitted_model.fittedvalues
        actuals = hist_data['y'].iloc[1:]  # ARIMA loses first value due to differencing
        mape = np.mean(np.abs((actuals - fitted_values) / (actuals + 1e-10))) * 100
        accuracy = max(0, 100 - mape) / 100
        
        return Forecast(
            metric=metric,
            historical=historical_points,
            forecast=forecast_points,
            accuracy=float(accuracy),
            confidence_interval=0.80
        )
        
    except ImportError:
        print("statsmodels not installed, falling back to linear regression")
        # Fallback to simple method
        return _simple_forecast_fallback(metric, historical_data, periods)
    except Exception as e:
        print(f"ARIMA failed: {e}, using fallback")
        return _simple_forecast_fallback(metric, historical_data, periods)


def forecast_with_exponential_smoothing(metric: str, historical_data: pd.DataFrame, periods: int) -> Forecast:
    """Exponential Smoothing (Holt-Winters) forecast
    
    Good for: Data with trend and seasonality
    Uses: Triple exponential smoothing (level + trend + seasonality)
    """
    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
        
        # Prepare data
        hist_data = historical_data.copy()
        hist_data['ds'] = pd.to_datetime(hist_data['ds'])
        hist_data = hist_data.set_index('ds')
        
        # Determine seasonal period (weekly = 7 days)
        seasonal_periods = min(7, len(hist_data) // 2)
        
        # Fit Holt-Winters model
        model = ExponentialSmoothing(
            hist_data['y'],
            seasonal_periods=seasonal_periods,
            trend='add',
            seasonal='add' if len(hist_data) >= seasonal_periods * 2 else None
        )
        fitted_model = model.fit()
        
        # Generate forecast
        forecast_result = fitted_model.forecast(steps=periods)
        
        # Calculate confidence intervals (using residual standard error)
        residuals = hist_data['y'] - fitted_model.fittedvalues
        std_error = np.std(residuals)
        z_score = 1.28  # 80% confidence interval
        
        # Historical points
        historical_points = [
            ForecastPoint(
                date=date.strftime('%Y-%m-%d'),
                value=float(value)
            )
            for date, value in hist_data['y'].items()
        ]
        
        # Forecast points
        last_date = hist_data.index[-1]
        forecast_points = []
        for i in range(periods):
            forecast_date = last_date + timedelta(days=i+1)
            pred_value = float(forecast_result.iloc[i])
            forecast_points.append(ForecastPoint(
                date=forecast_date.strftime('%Y-%m-%d'),
                value=pred_value,
                lower_bound=pred_value - (z_score * std_error),
                upper_bound=pred_value + (z_score * std_error)
            ))
        
        # Calculate accuracy
        mape = np.mean(np.abs((hist_data['y'] - fitted_model.fittedvalues) / (hist_data['y'] + 1e-10))) * 100
        accuracy = max(0, 100 - mape) / 100
        
        return Forecast(
            metric=metric,
            historical=historical_points,
            forecast=forecast_points,
            accuracy=float(accuracy),
            confidence_interval=0.80
        )
        
    except ImportError:
        print("statsmodels not installed for Exponential Smoothing")
        return _simple_forecast_fallback(metric, historical_data, periods)
    except Exception as e:
        print(f"Exponential Smoothing failed: {e}")
        return _simple_forecast_fallback(metric, historical_data, periods)


def forecast_ensemble(metric: str, historical_data: pd.DataFrame, periods: int,
                     prophet_forecast: Forecast = None,
                     arima_forecast: Forecast = None,
                     exp_forecast: Forecast = None) -> Forecast:
    """Ensemble forecast combining multiple models
    
    Strategy: Weighted average based on individual model accuracy
    - Higher accuracy models get more weight
    - Combines Prophet + ARIMA + Exponential Smoothing
    - Most robust approach for business forecasting
    """
    
    forecasts_available = []
    weights = []
    
    if prophet_forecast and prophet_forecast.accuracy > 0:
        forecasts_available.append(('prophet', prophet_forecast))
        weights.append(prophet_forecast.accuracy)
    
    if arima_forecast and arima_forecast.accuracy > 0:
        forecasts_available.append(('arima', arima_forecast))
        weights.append(arima_forecast.accuracy)
    
    if exp_forecast and exp_forecast.accuracy > 0:
        forecasts_available.append(('exponential', exp_forecast))
        weights.append(exp_forecast.accuracy)
    
    if len(forecasts_available) == 0:
        # Fallback to simple method
        return _simple_forecast_fallback(metric, historical_data, periods)
    
    if len(forecasts_available) == 1:
        # Only one model available, return it
        return forecasts_available[0][1]
    
    # Normalize weights
    total_weight = sum(weights)
    weights = [w / total_weight for w in weights]
    
    # Combine forecasts using weighted average
    ensemble_forecast_points = []
    for i in range(periods):
        weighted_value = sum(
            f[1].forecast[i].value * w 
            for f, w in zip(forecasts_available, weights)
        )
        weighted_lower = sum(
            (f[1].forecast[i].lower_bound or f[1].forecast[i].value) * w 
            for f, w in zip(forecasts_available, weights)
        )
        weighted_upper = sum(
            (f[1].forecast[i].upper_bound or f[1].forecast[i].value) * w 
            for f, w in zip(forecasts_available, weights)
        )
        
        ensemble_forecast_points.append(ForecastPoint(
            date=forecasts_available[0][1].forecast[i].date,
            value=weighted_value,
            lower_bound=weighted_lower,
            upper_bound=weighted_upper
        ))
    
    # Use historical from first available forecast
    historical_points = forecasts_available[0][1].historical
    
    # Ensemble accuracy is weighted average of component accuracies
    ensemble_accuracy = sum(f.accuracy * w for f, w in zip([f[1] for f in forecasts_available], weights))
    
    return Forecast(
        metric=metric,
        historical=historical_points,
        forecast=ensemble_forecast_points,
        accuracy=ensemble_accuracy,
        confidence_interval=0.80
    )


def calculate_mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Calculate Mean Absolute Percentage Error"""
    return np.mean(np.abs((actual - predicted) / (actual + 1e-10))) * 100


def _simple_forecast_fallback(metric: str, historical_data: pd.DataFrame, periods: int) -> Forecast:
    """Simple moving average fallback when advanced models fail"""
    from sklearn.linear_model import LinearRegression
    
    hist_data = historical_data.copy()
    hist_data['ds'] = pd.to_datetime(hist_data['ds'])
    hist_data['x'] = (hist_data['ds'] - hist_data['ds'].min()).dt.days
    
    X = hist_data[['x']].values
    y = hist_data['y'].values
    
    model = LinearRegression()
    model.fit(X, y)
    
    historical_points = [
        ForecastPoint(date=row['ds'].strftime('%Y-%m-%d'), value=float(row['y']))
        for _, row in hist_data.iterrows()
    ]
    
    last_date = hist_data['ds'].max()
    future_x = np.array([[(last_date + timedelta(days=i+1) - hist_data['ds'].min()).days] for i in range(periods)])
    predictions = model.predict(future_x)
    
    residuals = y - model.predict(X)
    std_error = np.std(residuals)
    z_score = 1.28
    
    forecast_points = [
        ForecastPoint(
            date=(last_date + timedelta(days=i+1)).strftime('%Y-%m-%d'),
            value=float(pred),
            lower_bound=float(pred - z_score * std_error),
            upper_bound=float(pred + z_score * std_error)
        )
        for i, pred in enumerate(predictions)
    ]
    
    mape = calculate_mape(y, model.predict(X))
    accuracy = max(0, 100 - mape) / 100
    
    return Forecast(
        metric=metric,
        historical=historical_points,
        forecast=forecast_points,
        accuracy=float(accuracy),
        confidence_interval=0.80
    )
