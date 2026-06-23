import { Component } from 'react';

/**
 * Top-level error boundary that prevents a single render throw from blanking
 * the entire dashboard. Renders a recovery UI instead of a white screen.
 */
export class AppErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error('[Atlas] Unhandled render error:', error, info.componentStack);
  }

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <div style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', minHeight: '100vh',
        background: '#0f1117', color: '#f1f5f9', fontFamily: 'Inter, system-ui, sans-serif',
        gap: 16, padding: 32,
      }}>
        <div style={{ fontSize: 48 }}>⚠</div>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>Something went wrong</h1>
        <p style={{ margin: 0, color: '#94a3b8', maxWidth: 480, textAlign: 'center' }}>
          An unexpected error occurred in the dashboard. Reload the page to continue.
          If the problem persists, contact your Atlas administrator.
        </p>
        <button
          onClick={() => window.location.reload()}
          style={{
            marginTop: 8, padding: '10px 24px', borderRadius: 8,
            background: '#3b82f6', color: '#fff', border: 'none',
            fontSize: 14, fontWeight: 600, cursor: 'pointer',
          }}
        >
          Reload
        </button>
        {import.meta.env.DEV && this.state.error && (
          <pre style={{
            marginTop: 16, padding: 16, borderRadius: 8,
            background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)',
            color: '#fca5a5', fontSize: 11, maxWidth: 640, overflowX: 'auto',
          }}>
            {this.state.error.toString()}
          </pre>
        )}
      </div>
    );
  }
}
