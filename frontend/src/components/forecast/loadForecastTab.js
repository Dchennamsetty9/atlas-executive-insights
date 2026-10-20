export function loadForecastTab(api, selection, publish, onError) {
  const { tab, model, forecastType, productLine, salesMarket, year, quarter } = selection;
  const tasks = [];
  const add = (field, request) => {
    const task = request.then(value => publish(field, value)).catch(error => onError(field, error));
    tasks.push(task);
  };

  if (tab === 'Overview' || tab === 'Plan Tracking') {
    add('weekly', api.getForecastV2Weekly(model, forecastType, null, productLine, salesMarket, year, quarter));
    add('ytd', api.getForecastV2YTD(forecastType, null, productLine, salesMarket, year, quarter, model));
    add('models', api.getForecastV2Models());
    add('freshness', api.getForecastV2Freshness());
    add('confidenceBands', api.getForecastV2ConfidenceBands(forecastType, productLine, year, quarter, model, salesMarket));
    add('runDelta', api.getForecastV2RunDelta(productLine, salesMarket));
    add('yearRows', Promise.allSettled([
      api.getForecastV2Weekly(model, 'rolling', null, productLine, salesMarket, year, null),
      api.getForecastV2Weekly(model, 'roy', null, productLine, salesMarket, year, null),
    ]).then(([rolling, roy]) => {
      if (rolling.status === 'rejected') throw rolling.reason;
      if (roy.status === 'rejected') throw roy.reason;
      return { rolling: rolling.value, roy: roy.value };
    }));
    if (tab === 'Overview') add('paceOutlook', api.getForecastV2PaceOutlook(productLine));
    if (tab === 'Plan Tracking') add('driverBridge', api.getForecastV2DriverBridge(year, quarter, model, productLine, salesMarket));
  } else if (tab === 'Multi-Year') {
    add('historical', api.getForecastV2Historical(null, productLine, salesMarket, null, model));
    add('weekly', api.getForecastV2Weekly(model, forecastType, null, productLine, salesMarket, year, quarter));
  } else if (tab === 'By Product') {
    add('byProduct', api.getForecastV2ByProduct(model, forecastType, null, productLine, salesMarket, year, quarter));
  } else if (tab === 'Monthly') {
    add('monthly', api.getForecastV2Monthly(forecastType, null, productLine, salesMarket, year, quarter, model));
  } else if (tab === 'Exec Mode') {
    add('weekly', api.getForecastV2Weekly(model, forecastType, null, productLine, salesMarket, year, quarter));
    add('confidenceBands', api.getForecastV2ConfidenceBands(forecastType, productLine, year, quarter, model, salesMarket));
    add('confidence', api.getForecastV2Confidence(model, year, quarter, productLine, salesMarket));
    add('driverBridge', api.getForecastV2DriverBridge(year, quarter, model, productLine, salesMarket));
    add('riskRadar', api.getForecastV2RiskRadar(forecastType, year, quarter, 20, model, productLine, salesMarket));
    add('meetingMode', api.getForecastV2MeetingMode(model, year, quarter, productLine, salesMarket));
    add('actions', api.getActions('pending'));
    add('governanceLog', api.getForecastV2GovernanceLog());
    add('runDelta', api.getForecastV2RunDelta(productLine, salesMarket));
    add('scenarioGrid', api.getForecastV2ScenarioGrid(productLine, salesMarket, quarter));
    add('sensitivity', api.getForecastV2Sensitivity(productLine, salesMarket));
    add('modelScenarios', api.getForecastV2ModelScenarios(productLine));
    add('historicalScenarios', api.getForecastV2HistoricalScenarios(productLine, salesMarket, year));
  }
  return Promise.allSettled(tasks);
}