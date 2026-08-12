/**
 * ProductWheel — Interactive rotating product selector
 * Drag/click to rotate; selected product propagates up via onSelect.
 * Products are sourced from the /api/filters response (same as FilterPanel).
 */

import { useState, useRef, useCallback, memo } from 'react';
import { motion } from 'framer-motion';

// Product colors (matches brand palette)
const PRODUCT_COLORS = {
  All:     '#3b82f6',
  Connect: '#10b981',
  Engage:  '#f59e0b',
  Rescue:  '#ef4444',
  Central: '#8b5cf6',
  Resolve: '#06b6d4',
};

const DEFAULT_PRODUCTS = [
  { value: 'All',     label: 'All Products' },
  { value: 'Connect', label: 'Connect'      },
  { value: 'Engage',  label: 'Engage'       },
  { value: 'Rescue',  label: 'Rescue'       },
  { value: 'Central', label: 'Central'      },
  { value: 'Resolve', label: 'Resolve'      },
];

const RADIUS   = 72;   // px — orbit radius
const ITEM_SIZE = 36;  // px — item circle diameter

// Convert index + rotation offset to x/y position on circle
function getPos(i, total, rotationDeg) {
  const angle = (360 / total) * i + rotationDeg - 90;
  const rad   = (angle * Math.PI) / 180;
  return {
    x: Math.cos(rad) * RADIUS,
    y: Math.sin(rad) * RADIUS,
  };
}

const ProductWheel = ({ selected = 'All', onSelect, products: propProducts }) => {
  const products     = propProducts?.length ? propProducts : DEFAULT_PRODUCTS;
  const total        = products.length;
  const [rotation, setRotation]   = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const dragStart    = useRef(null);
  const rotStart     = useRef(0);
  const containerRef = useRef(null);

  // Snap to nearest item after drag
  const snapToNearest = useCallback((currentRot) => {
    const step  = 360 / total;
    const snapped = Math.round(currentRot / step) * step;
    setRotation(snapped);
    // Derive selected product from snapped angle
    const idx = ((- Math.round(snapped / step)) % total + total) % total;
    onSelect?.(products[idx].value);
  }, [total, products, onSelect]);

  const handleDragStart = useCallback((e) => {
    setIsDragging(true);
    const rect   = containerRef.current?.getBoundingClientRect();
    const cx     = rect ? rect.left + rect.width / 2 : 0;
    const cy     = rect ? rect.top  + rect.height / 2 : 0;
    const clientX = e.touches?.[0]?.clientX ?? e.clientX;
    const clientY = e.touches?.[0]?.clientY ?? e.clientY;
    dragStart.current = Math.atan2(clientY - cy, clientX - cx) * (180 / Math.PI);
    rotStart.current  = rotation;
  }, [rotation]);

  const handleDragMove = useCallback((e) => {
    if (!isDragging || dragStart.current == null) return;
    const rect   = containerRef.current?.getBoundingClientRect();
    const cx     = rect ? rect.left + rect.width / 2 : 0;
    const cy     = rect ? rect.top  + rect.height / 2 : 0;
    const clientX = e.touches?.[0]?.clientX ?? e.clientX;
    const clientY = e.touches?.[0]?.clientY ?? e.clientY;
    const currentAngle = Math.atan2(clientY - cy, clientX - cx) * (180 / Math.PI);
    const delta = currentAngle - dragStart.current;
    setRotation(rotStart.current + delta);
  }, [isDragging]);

  const handleDragEnd = useCallback(() => {
    setIsDragging(false);
    snapToNearest(rotation);
  }, [rotation, snapToNearest]);

  const handleItemClick = useCallback((idx) => {
    if (isDragging) return;
    const step     = 360 / total;
    const target   = -idx * step;
    setRotation(target);
    onSelect?.(products[idx].value);
  }, [isDragging, total, products, onSelect]);

  const wheelSize = (RADIUS + ITEM_SIZE) * 2 + 16;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
      <div style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: 1 }}>
        Product
      </div>

      {/* Wheel container */}
      <div
        ref={containerRef}
        style={{
          position: 'relative',
          width:  wheelSize,
          height: wheelSize,
          cursor: isDragging ? 'grabbing' : 'grab',
          userSelect: 'none',
          touchAction: 'none',
        }}
        onMouseDown={handleDragStart}
        onMouseMove={handleDragMove}
        onMouseUp={handleDragEnd}
        onMouseLeave={handleDragEnd}
        onTouchStart={handleDragStart}
        onTouchMove={handleDragMove}
        onTouchEnd={handleDragEnd}
      >
        {/* Orbit ring */}
        <div style={{
          position: 'absolute',
          top:  '50%',
          left: '50%',
          width:  RADIUS * 2,
          height: RADIUS * 2,
          marginLeft: -RADIUS,
          marginTop:  -RADIUS,
          borderRadius: '50%',
          border: '1px dashed rgba(255,255,255,0.08)',
        }} />

        {/* Center selected label */}
        <div style={{
          position: 'absolute',
          top: '50%', left: '50%',
          transform: 'translate(-50%,-50%)',
          textAlign: 'center',
          pointerEvents: 'none',
        }}>
          <div style={{
            width: 44, height: 44,
            borderRadius: '50%',
            background: `radial-gradient(circle, ${PRODUCT_COLORS[selected] ?? '#3b82f6'}33 0%, transparent 70%)`,
            border: `2px solid ${PRODUCT_COLORS[selected] ?? '#3b82f6'}66`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: `0 0 16px ${PRODUCT_COLORS[selected] ?? '#3b82f6'}44`,
          }}>
            <span style={{ fontSize: 8, color: PRODUCT_COLORS[selected] ?? '#3b82f6', fontWeight: 700, textAlign: 'center', lineHeight: 1.2 }}>
              {selected === 'All' ? 'ALL' : selected.toUpperCase().slice(0,3)}
            </span>
          </div>
        </div>

        {/* Orbiting items */}
        {products.map((p, i) => {
          const pos     = getPos(i, total, rotation);
          const isActive = p.value === selected;
          const clr     = PRODUCT_COLORS[p.value] ?? '#3b82f6';

          return (
            <motion.div
              key={p.value}
              style={{
                position: 'absolute',
                top:  '50%',
                left: '50%',
                width:  ITEM_SIZE,
                height: ITEM_SIZE,
                marginLeft: -ITEM_SIZE / 2,
                marginTop:  -ITEM_SIZE / 2,
                x: pos.x,
                y: pos.y,
                borderRadius: '50%',
                background:  isActive ? `${clr}22` : 'rgba(255,255,255,0.04)',
                border: isActive
                  ? `2px solid ${clr}`
                  : '1px solid rgba(255,255,255,0.1)',
                boxShadow: isActive ? `0 0 12px ${clr}66` : 'none',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
                zIndex: isActive ? 2 : 1,
              }}
              animate={{ x: pos.x, y: pos.y }}
              transition={{ type: 'spring', stiffness: 200, damping: 22 }}
              onClick={() => handleItemClick(i)}
              title={p.label}
            >
              <span style={{
                fontSize: 8,
                fontWeight: 700,
                color: isActive ? clr : '#64748b',
                textAlign: 'center',
                lineHeight: 1.2,
                pointerEvents: 'none',
              }}>
                {p.value === 'All' ? 'ALL' : p.value.slice(0, 3).toUpperCase()}
              </span>
            </motion.div>
          );
        })}
      </div>

      {/* Selected label */}
      <div style={{
        fontSize: 11,
        fontWeight: 600,
        color: PRODUCT_COLORS[selected] ?? '#3b82f6',
        letterSpacing: 0.5,
      }}>
        {products.find(p => p.value === selected)?.label ?? selected}
      </div>
    </div>
  );
};

export default memo(ProductWheel);
