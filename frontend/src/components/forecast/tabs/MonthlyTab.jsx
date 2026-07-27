import MonthlyTable from '../charts/MonthlyTable';
import { CardWrap, EmptyState, GraphInsight, SectionTitle, Skeleton } from '../common';

const MonthlyTab = ({ loading, monthlyView, graphInsights }) => {
  return (
    <CardWrap>
      <SectionTitle>Monthly Actuals vs Forecast Scenarios</SectionTitle>
      <GraphInsight summary={graphInsights.monthly} chartType="monthly_forecast" metricName="Monthly Growth ARR — actuals vs forecast scenarios" dataPoints={monthlyView} />
      {loading ? <Skeleton height={300} /> : monthlyView && monthlyView.length > 0 ? <MonthlyTable months={monthlyView} /> : <EmptyState />}
    </CardWrap>
  );
};

export default MonthlyTab;
