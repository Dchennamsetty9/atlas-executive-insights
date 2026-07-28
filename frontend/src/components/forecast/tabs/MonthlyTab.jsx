import MonthlyTable from '../charts/MonthlyTable';
import { CardWrap, EmptyState, GraphInsight, SectionTitle, TableSkeleton } from '../common';

const MonthlyTab = ({ loading, monthlyView, graphInsights, runDate }) => {
  return (
    <CardWrap downloadName="monthly_actuals_forecast">
      <SectionTitle>Monthly Actuals vs Forecast Scenarios {runDate && <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 400 }}>— as of {runDate}</span>}</SectionTitle>
      <GraphInsight summary={graphInsights.monthly} chartType="monthly_forecast" metricName="Monthly Growth ARR — actuals vs forecast scenarios" dataPoints={monthlyView} />
      {loading ? <TableSkeleton rowCount={12} columnCount={8} /> : monthlyView && monthlyView.length > 0 ? <MonthlyTable months={monthlyView} /> : <EmptyState />}
    </CardWrap>
  );
};

export default MonthlyTab;
