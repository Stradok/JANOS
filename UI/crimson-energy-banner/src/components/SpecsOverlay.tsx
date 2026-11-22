import React from 'react';
import { AspectGuideMode } from '../types';
import { ShieldCheck, Grid, CheckCircle2 } from 'lucide-react';

interface SpecsOverlayProps {
  guideMode: AspectGuideMode;
  onGuideChange: (mode: AspectGuideMode) => void;
}

export const SpecsOverlay: React.FC<SpecsOverlayProps> = ({
  guideMode,
  onGuideChange,
}) => {
  return (
    <div className="bg-[#08080c] ring-1 ring-white/10 rounded-sm p-6 shadow-2xl space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/5 pb-4">
        <div className="flex items-center gap-3">
          <div className="w-5 h-5 border border-[#ef233c] rotate-45 flex items-center justify-center shrink-0">
            <div className="w-1.5 h-1.5 bg-[#ef233c] -rotate-45" />
          </div>
          <div>
            <h3 className="text-xs uppercase tracking-[0.3em] font-light text-white">
              Composition & Dimension Metrics
            </h3>
            <p className="text-[10px] text-white/40 font-mono tracking-wider">
              Ultra-wide frame specifications & geometric ratio diagnostics
            </p>
          </div>
        </div>

        {/* Guide mode toggle buttons */}
        <div className="flex items-center gap-1.5 bg-black/40 p-1 rounded-sm ring-1 ring-white/10">
          <button
            onClick={() => onGuideChange('none')}
            id="guide-mode-none"
            className={`px-3 py-1 text-[10px] uppercase tracking-[0.2em] font-mono rounded-sm transition-all ${
              guideMode === 'none'
                ? 'bg-[#ef233c] text-white font-medium shadow-sm'
                : 'text-white/40 hover:text-white'
            }`}
          >
            Clean Art
          </button>
          <button
            onClick={() => onGuideChange('composition-grid')}
            id="guide-mode-grid"
            className={`flex items-center gap-1.5 px-3 py-1 text-[10px] uppercase tracking-[0.2em] font-mono rounded-sm transition-all ${
              guideMode === 'composition-grid'
                ? 'bg-[#ef233c] text-white font-medium shadow-sm'
                : 'text-white/40 hover:text-white'
            }`}
          >
            <Grid className="w-3 h-3" />
            <span>1/3 & 2/3 Rule</span>
          </button>
          <button
            onClick={() => onGuideChange('safety-margins')}
            id="guide-mode-safety"
            className={`flex items-center gap-1.5 px-3 py-1 text-[10px] uppercase tracking-[0.2em] font-mono rounded-sm transition-all ${
              guideMode === 'safety-margins'
                ? 'bg-[#ef233c] text-white font-medium shadow-sm'
                : 'text-white/40 hover:text-white'
            }`}
          >
            <ShieldCheck className="w-3 h-3" />
            <span>200px Margin</span>
          </button>
          <button
            onClick={() => onGuideChange('all')}
            id="guide-mode-all"
            className={`px-3 py-1 text-[10px] uppercase tracking-[0.2em] font-mono rounded-sm transition-all ${
              guideMode === 'all'
                ? 'bg-[#ef233c] text-white font-medium shadow-sm'
                : 'text-white/40 hover:text-white'
            }`}
          >
            All Guides
          </button>
        </div>
      </div>

      {/* Grid of verified specifications */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs">
        <div className="bg-black/40 border border-white/5 rounded-sm p-3.5">
          <div className="text-white/30 font-mono text-[9px] uppercase tracking-widest">01. Resolution</div>
          <div className="text-white font-mono font-medium text-sm mt-1">1584 × 396 px</div>
          <div className="text-[#ef233c] text-[10px] font-mono mt-1.5 flex items-center gap-1.5">
            <CheckCircle2 className="w-3 h-3" /> 5.9:1 Ultra-Wide
          </div>
        </div>

        <div className="bg-black/40 border border-white/5 rounded-sm p-3.5">
          <div className="text-white/30 font-mono text-[9px] uppercase tracking-widest">02. Sphere Axis</div>
          <div className="text-white font-mono font-medium text-sm mt-1">Right-of-Center (67%)</div>
          <div className="text-[#ef233c] text-[10px] font-mono mt-1.5 flex items-center gap-1.5">
            <CheckCircle2 className="w-3 h-3" /> 2/3 Axis (1056px)
          </div>
        </div>

        <div className="bg-black/40 border border-white/5 rounded-sm p-3.5">
          <div className="text-white/30 font-mono text-[9px] uppercase tracking-widest">03. Negative Space</div>
          <div className="text-white font-mono font-medium text-sm mt-1">Left 1/3 (0–528px)</div>
          <div className="text-[#ef233c] text-[10px] font-mono mt-1.5 flex items-center gap-1.5">
            <CheckCircle2 className="w-3 h-3" /> &gt;200px Clean Void
          </div>
        </div>

        <div className="bg-black/40 border border-white/5 rounded-sm p-3.5">
          <div className="text-white/30 font-mono text-[9px] uppercase tracking-widest">04. Color System</div>
          <div className="flex items-center gap-2 mt-1.5">
            <div className="w-3.5 h-3.5 rounded-sm border border-white/20 bg-[#050506]" title="#050506 Void" />
            <div className="w-3.5 h-3.5 rounded-sm border border-white/20 bg-[#ef233c]" title="#ef233c Crimson" />
            <div className="w-3.5 h-3.5 rounded-sm border border-white/20 bg-white" title="#ffffff Core" />
            <span className="text-white/80 font-mono text-[10px]">#ef233c Crimson</span>
          </div>
          <div className="text-[#ef233c] text-[10px] font-mono mt-1.5 flex items-center gap-1.5">
            <CheckCircle2 className="w-3 h-3" /> Monochromatic
          </div>
        </div>
      </div>
    </div>
  );
};
