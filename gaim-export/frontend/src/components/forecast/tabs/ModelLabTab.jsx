import { useState } from 'react';
import ModelLabSection from '../ModelLabSection';

const ModelLabTab = ({ prodLine, salesMarket }) => {
  const [showDiagnostic, setShowDiagnostic] = useState(false);

  return (
    <>
      {prodLine === 'All' && (
        <div style={{ padding: '8px 14px', marginBottom: 12, borderRadius: 8, fontSize: 12, color: '#93c5fd', background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.2)' }}>
          ℹ Model Lab is per product line (the V5 models run separately for UCC and ITSG). Showing <b>UCC</b> — pick UCC or ITSG in the PRODUCT selector to switch.
        </div>
      )}
      <div style={{ marginBottom: 12 }}>
        <button
          onClick={() => setShowDiagnostic((v) => !v)}
          style={{
            padding: '6px 12px',
            borderRadius: 8,
            border: '1px solid rgba(148,163,184,0.35)',
            background: 'rgba(148,163,184,0.08)',
            color: '#cbd5e1',
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: '0.03em',
            textTransform: 'uppercase',
            cursor: 'pointer',
          }}
        >
          {showDiagnostic ? 'Hide Diagnostic' : 'Show Diagnostic'}
        </button>
      </div>
      {showDiagnostic && <ModelLabSection product={prodLine === 'ITSG' ? 'ITSG' : 'UCC'} salesMarket={salesMarket} />}
    </>
  );
};

export default ModelLabTab;
