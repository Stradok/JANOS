import React from 'react';
import { BannerConfig } from '../types';
import { Sparkles, Sliders, RefreshCw, Zap, Flame, Play, Pause, Compass } from 'lucide-react';

interface BannerControlsProps {
  config: BannerConfig;
  onChange: (newConfig: BannerConfig) => void;
  onReset: () => void;
}

export const BannerControls: React.FC<BannerControlsProps> = ({
  config,
  onChange,
  onReset,
}) => {
  const update = <K extends keyof BannerConfig>(key: K, value: BannerConfig[K]) => {
    onChange({ ...config, [key]: value });
  };

  const reRollSeed = () => {
    update('seed', Math.floor(Math.random() * 100000));
  };

  const togglePlay = () => {
    update('speed', config.speed === 0 ? 1 : 0);
  };

  return (
    <div className="bg-[#08080c] ring-1 ring-white/10 rounded-sm p-6 shadow-2xl space-y-6">
      <div className="flex flex-wrap items-center justify-between border-b border-white/5 pb-4 gap-3">
        <div className="flex items-center gap-3">
          <div className="w-5 h-5 border border-[#ef233c] rotate-45 flex items-center justify-center shrink-0">
            <div className="w-1.5 h-1.5 bg-[#ef233c] -rotate-45" />
          </div>
          <div>
            <h3 className="text-xs uppercase tracking-[0.3em] font-light text-white">
              Procedural Energy Engine
            </h3>
            <p className="text-[10px] text-white/40 font-mono tracking-wider">
              Real-time filament turbulence & volumetric radiation parameters
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={togglePlay}
            id="toggle-sim-playback-btn"
            className="flex items-center gap-1.5 px-4 py-2 bg-transparent hover:bg-white/5 text-[10px] font-mono uppercase tracking-[0.2em] text-white/80 rounded-sm border border-white/20 hover:border-[#ef233c] transition-colors"
            title={config.speed === 0 ? 'Resume simulation' : 'Freeze simulation'}
          >
            {config.speed === 0 ? <Play className="w-3 h-3 text-[#ef233c]" /> : <Pause className="w-3 h-3 text-white/60" />}
            <span>{config.speed === 0 ? 'Resume' : 'Freeze'}</span>
          </button>

          <button
            onClick={reRollSeed}
            id="reroll-seed-btn"
            className="flex items-center gap-1.5 px-4 py-2 bg-transparent hover:bg-white/5 text-[10px] font-mono uppercase tracking-[0.2em] text-white/80 rounded-sm border border-white/20 hover:border-[#ef233c] transition-colors"
            title="Generate new chaotic strand variation"
          >
            <RefreshCw className="w-3 h-3 text-[#ef233c]" />
            <span>Reseed</span>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {/* Sphere Position & Framing */}
        <div className="space-y-4 bg-black/40 p-4 rounded-sm border border-white/5">
          <div className="flex items-center justify-between text-[10px] uppercase tracking-[0.2em] font-light text-white/70">
            <span className="flex items-center gap-1.5">
              <Compass className="w-3 h-3 text-[#ef233c]" />
              Framing & Axis
            </span>
            <span className="font-mono text-[#ef233c]">{Math.round(config.sphereX * 100)}%</span>
          </div>

          <div className="space-y-2">
            <div className="flex justify-between text-[10px] font-mono text-white/40">
              <span>Horizontal Center (2/3)</span>
              <span className="text-white/80 font-mono">{(config.sphereX * 1584).toFixed(0)}px</span>
            </div>
            <input
              type="range"
              min="0.4"
              max="0.85"
              step="0.01"
              value={config.sphereX}
              onChange={(e) => update('sphereX', parseFloat(e.target.value))}
              className="w-full accent-[#ef233c] bg-white/10 h-1 rounded-sm appearance-none cursor-pointer"
            />
            <div className="flex justify-between text-[8px] text-white/30 font-mono uppercase tracking-wider">
              <span>Mid (50%)</span>
              <span className="text-[#ef233c]/90">Target (67%)</span>
              <span>Right (85%)</span>
            </div>
          </div>

          <div className="space-y-2 pt-1">
            <div className="flex justify-between text-[10px] font-mono text-white/40">
              <span>Sphere Radius</span>
              <span className="text-[#ef233c] font-mono">{config.sphereRadius}px</span>
            </div>
            <input
              type="range"
              min="50"
              max="160"
              step="1"
              value={config.sphereRadius}
              onChange={(e) => update('sphereRadius', parseInt(e.target.value))}
              className="w-full accent-[#ef233c] bg-white/10 h-1 rounded-sm appearance-none cursor-pointer"
            />
          </div>
        </div>

        {/* Core & Volumetric Glow */}
        <div className="space-y-4 bg-black/40 p-4 rounded-sm border border-white/5">
          <div className="flex items-center justify-between text-[10px] uppercase tracking-[0.2em] font-light text-white/70">
            <span className="flex items-center gap-1.5">
              <Flame className="w-3 h-3 text-[#ef233c]" />
              Radiation & Core
            </span>
            <span className="font-mono text-[#ef233c]">{config.coreIntensity.toFixed(1)}x</span>
          </div>

          <div className="space-y-2">
            <div className="flex justify-between text-[10px] font-mono text-white/40">
              <span>White-Hot Core Intensity</span>
              <span className="text-white/80 font-mono">{config.coreIntensity.toFixed(1)}x</span>
            </div>
            <input
              type="range"
              min="0.5"
              max="2.0"
              step="0.1"
              value={config.coreIntensity}
              onChange={(e) => update('coreIntensity', parseFloat(e.target.value))}
              className="w-full accent-[#ef233c] bg-white/10 h-1 rounded-sm appearance-none cursor-pointer"
            />
          </div>

          <div className="space-y-2 pt-1">
            <div className="flex justify-between text-[10px] font-mono text-white/40">
              <span>Volumetric Red Glow Spread</span>
              <span className="text-[#ef233c] font-mono">{config.volumetricGlowRadius}px</span>
            </div>
            <input
              type="range"
              min="100"
              max="450"
              step="10"
              value={config.volumetricGlowRadius}
              onChange={(e) => update('volumetricGlowRadius', parseInt(e.target.value))}
              className="w-full accent-[#ef233c] bg-white/10 h-1 rounded-sm appearance-none cursor-pointer"
            />
          </div>
        </div>

        {/* Chaotic Strands & Particles */}
        <div className="space-y-4 bg-black/40 p-4 rounded-sm border border-white/5 md:col-span-2 lg:col-span-1">
          <div className="flex items-center justify-between text-[10px] uppercase tracking-[0.2em] font-light text-white/70">
            <span className="flex items-center gap-1.5">
              <Zap className="w-3 h-3 text-[#ef233c]" />
              Strands & Dust
            </span>
            <span className="font-mono text-[#ef233c]">{config.sparkCount} str</span>
          </div>

          <div className="space-y-2">
            <div className="flex justify-between text-[10px] font-mono text-white/40">
              <span>Chaotic Outward Strands</span>
              <span className="text-white/80 font-mono">{config.sparkCount} sparks</span>
            </div>
            <input
              type="range"
              min="10"
              max="60"
              step="2"
              value={config.sparkCount}
              onChange={(e) => update('sparkCount', parseInt(e.target.value))}
              className="w-full accent-[#ef233c] bg-white/10 h-1 rounded-sm appearance-none cursor-pointer"
            />
          </div>

          <div className="space-y-2 pt-1">
            <div className="flex justify-between text-[10px] font-mono text-white/40">
              <span>Atmospheric Particle Dust</span>
              <span className="text-[#ef233c] font-mono">{config.particleDustCount} pts</span>
            </div>
            <input
              type="range"
              min="100"
              max="800"
              step="50"
              value={config.particleDustCount}
              onChange={(e) => update('particleDustCount', parseInt(e.target.value))}
              className="w-full accent-[#ef233c] bg-white/10 h-1 rounded-sm appearance-none cursor-pointer"
            />
          </div>
        </div>
      </div>

      {/* Preset Quick Actions */}
      <div className="flex flex-wrap items-center justify-between gap-4 pt-2 border-t border-white/5">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="text-[9px] font-mono uppercase tracking-[0.2em] text-white/30">Presets:</span>
          <button
            onClick={() => {
              onChange({
                ...config,
                sphereX: 0.67,
                sphereRadius: 95,
                coreIntensity: 1.2,
                filamentDensity: 65,
                filamentTurbulence: 1.0,
                sparkCount: 36,
                sparkLength: 120,
                particleDustCount: 380,
                volumetricGlowRadius: 280,
                cragginess: 0.45,
                speed: 1,
              });
            }}
            id="preset-prompt-exact"
            className="px-3 py-1.5 bg-transparent hover:bg-white/5 border border-white/15 hover:border-[#ef233c] text-[9px] uppercase tracking-[0.2em] font-mono text-white/80 rounded-sm transition-colors"
          >
            Prompt Exact (2/3 Ratio)
          </button>

          <button
            onClick={() => {
              onChange({
                ...config,
                sphereX: 0.72,
                sphereRadius: 110,
                coreIntensity: 1.7,
                sparkCount: 52,
                sparkLength: 160,
                volumetricGlowRadius: 360,
                cragginess: 0.65,
                particleDustCount: 600,
                speed: 1.3,
              });
            }}
            id="preset-high-turbulence"
            className="px-3 py-1.5 bg-transparent hover:bg-white/5 border border-white/15 hover:border-[#ef233c] text-[9px] uppercase tracking-[0.2em] font-mono text-white/80 rounded-sm transition-colors"
          >
            Solar Flare / Chaos
          </button>

          <button
            onClick={() => {
              onChange({
                ...config,
                sphereX: 0.65,
                sphereRadius: 80,
                coreIntensity: 0.9,
                sparkCount: 18,
                sparkLength: 90,
                volumetricGlowRadius: 200,
                cragginess: 0.25,
                particleDustCount: 220,
                speed: 0.7,
              });
            }}
            id="preset-minimal-void"
            className="px-3 py-1.5 bg-transparent hover:bg-white/5 border border-white/15 hover:border-[#ef233c] text-[9px] uppercase tracking-[0.2em] font-mono text-white/80 rounded-sm transition-colors"
          >
            Minimal Deep Space
          </button>
        </div>

        <button
          onClick={onReset}
          id="reset-defaults-btn"
          className="text-[9px] uppercase tracking-[0.2em] font-mono text-white/30 hover:text-white transition-colors"
        >
          Reset Default Configuration
        </button>
      </div>
    </div>
  );
};
