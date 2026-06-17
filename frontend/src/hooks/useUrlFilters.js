/**
 * useUrlFilters — bidirectional sync between FilterContext and URL search params.
 *
 * Any filter change writes to ?geo=EMEA&channel=Enterprise&... so users can share
 * a shareable link that opens the exact filtered view.
 *
 * Usage:
 *   Call once at the top of AppInner. It reads URL params on mount and patches
 *   the FilterContext; subsequent filter changes write back to the URL.
 */

import { useEffect } from 'react';
import { useFilters } from '../contexts/FilterContext';

const PARAM_KEYS = ['geo', 'channel', 'product', 'fuel', 'purchaseType', 'targetVersion', 'period'];

export function useUrlFilters() {
  const { filters, updateFilter } = useFilters();

  // On mount: read URL params → patch context
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    let changed = false;
    for (const key of PARAM_KEYS) {
      const val = params.get(key);
      if (val && val !== filters[key]) {
        updateFilter(key, val);
        changed = true;
      }
    }
    // Suppress lint — intentional one-time mount read
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // On filter change: write back to URL without triggering a navigation
  useEffect(() => {
    const params = new URLSearchParams();
    const defaults = {
      geo: 'All', channel: 'All', product: 'All',
      fuel: 'All', purchaseType: 'All', targetVersion: 'Plan', period: 'QTD',
    };

    for (const key of PARAM_KEYS) {
      if (filters[key] && filters[key] !== defaults[key]) {
        params.set(key, filters[key]);
      }
    }

    const search = params.toString();
    const newUrl = search
      ? `${window.location.pathname}?${search}`
      : window.location.pathname;

    window.history.replaceState(null, '', newUrl);
  }, [filters]);
}
