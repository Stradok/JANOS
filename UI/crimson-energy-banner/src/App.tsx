/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useRef } from 'react';
import { BannerCanvas, BannerCanvasHandle } from './components/BannerCanvas';
import { BannerControls } from './components/BannerControls';
import { SpecsOverlay } from './components/SpecsOverlay';
import { PlatformMockup } from './components/PlatformMockup';
import { ExportModal } from './components/ExportModal';
import { BannerConfig, ViewMode, PlatformMockupType, AspectGuideMode } from './types';
import {
  Download,
  Maximize2,
  Minimize2,
  Sparkles,
  Layers,
  Cpu,
  Columns,
  Share2,
  Info,
  Flame,
  Check,
  Copy,
  ExternalLink,
} from 'lucide-react';

const DEFAULT_CONFIG: BannerConfig = {
  sphereX: 0.67, // 2/3 right-of-center
  sphereY: 0.5,
  sphereRadius: 95,
  coreIntensity: 1.2,
  filamentDensity: 65,
  filamentTurbulence: 1.0,
  sparkCount: 36,
  sparkLength: 125,
  particleDustCount: 380,
  volumetricGlowRadius: 280,
  cragginess: 0.45,
  accentColor: '#ef233c',
  backgroundColor: '#050506',
  speed: 1,
  seed: 424242,
};

export default function App() {
  const [config, setConfig] = useState<BannerConfig>(DEFAULT_CONFIG);
  const [viewMode, setViewMode] = useState<ViewMode>('rendered-3d');
  const [mockup, setMockup] = useState<PlatformMockupType>('none');
  const [guides, setGuides] = useState<AspectGuideMode>('none');
  const [splitPos, setSplitPos] = useState<number>(50);
  const [isExportOpen, setIsExportOpen] = useState<boolean>(false);
  const [isFullscreen, setIsFullscreen] = useState<boolean>(false);
  const [copiedNotification, setCopiedNotification] = useState<boolean>(false);

  const canvasHandleRef = useRef<BannerCanvasHandle | null>(null);

  const handleReset = () => {
    setConfig(DEFAULT_CONFIG);
  };

  const handleQuickCopy = async () => {
    if (!canvasHandleRef.current) return;
    try {
      const dataUrl = canvasHandleRef.current.exportImage(1);
      const res = await fetch(dataUrl);
      const blob = await res.blob();
      await navigator.clipboard.write([
        new ClipboardItem({
          [blob.type]: blob,
        }),
      ]);
      setCopiedNotification(true);
      setTimeout(() => setCopiedNotification(false), 2000);
    } catch (e) {
      console.error(e);
    }
  };

  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().then(() => setIsFullscreen(true)).catch(() => {});
    } else {
      document.exitFullscreen().then(() => setIsFullscreen(false)).catch(() => {});
    }
  };

  return (
    <div className="min-h-screen bg-[#050506] text-white flex flex-col font-sans relative selection:bg-[#ef233c] selection:text-white">
      {/* Subtle Atmospheric Ambient Star Dust Background */}
      <div className="fixed inset-0 pointer-events-none opacity-25 z-0">
        <div className="absolute top-20 left-40 w-1 h-1 bg-white rounded-full opacity-40"></div>
        <div className="absolute bottom-40 right-20 w-1 h-1 bg-white rounded-full opacity-20"></div>
        <div className="absolute top-60 right-1/3 w-0.5 h-0.5 bg-white rounded-full opacity-30"></div>
        <div className="absolute top-1/4 left-1/4 w-0.5 h-0.5 bg-[#ef233c] rounded-full opacity-40"></div>
        <div className="absolute bottom-24 left-1/2 w-1 h-1 bg-white rounded-full opacity-15"></div>
      </div>

      {/* Top Header Navigation */}
      <header className="sticky top-0 z-40 bg-[#050506]/90 backdrop-blur-md border-b border-white/5 px-6 lg:px-12 py-5 flex items-center justify-between">
        <div className="flex items-center gap-5">
          {/* Rotated Diamond Monogram */}
          <div className="w-5 h-5 border border-[#ef233c] rotate-45 shrink-0 transition-transform duration-500 hover:rotate-90"></div>
          <div>
            <div className="flex items-center gap-3">
              <span className="text-xs uppercase tracking-[0.4em] font-light text-white">Aethel.Gard</span>
              <span className="text-[10px] font-mono tracking-widest text-[#ef233c] px-2 py-0.5 border border-[#ef233c]/30 rounded-sm bg-[#ef233c]/10">
                1584 &bull; 0396
              </span>
            </div>
            <p className="text-[9px] uppercase tracking-[0.25em] text-white/40 font-light hidden sm:block mt-0.5">
              Visual Systems Lab &bull; Deep-Space Energy Anomaly
            </p>
          </div>
        </div>

        {/* Action Controls in Header */}
        <div className="flex items-center gap-3">
          {/* View mode toggle pill */}
          <div className="flex items-center bg-black/40 p-1 rounded-sm ring-1 ring-white/10">
            <button
              onClick={() => setViewMode('rendered-3d')}
              id="view-mode-3d-btn"
              className={`flex items-center gap-1.5 px-3 py-1 text-[10px] uppercase tracking-[0.2em] rounded-sm transition-all ${
                viewMode === 'rendered-3d'
                  ? 'bg-[#ef233c] text-white font-medium shadow-sm'
                  : 'text-white/40 hover:text-white'
              }`}
              title="Studio-Quality 3D Render Artwork"
            >
              <Sparkles className="w-3 h-3" />
              <span className="hidden md:inline">3D Artwork</span>
            </button>
            <button
              onClick={() => setViewMode('procedural-live')}
              id="view-mode-live-btn"
              className={`flex items-center gap-1.5 px-3 py-1 text-[10px] uppercase tracking-[0.2em] rounded-sm transition-all ${
                viewMode === 'procedural-live'
                  ? 'bg-[#ef233c] text-white font-medium shadow-sm'
                  : 'text-white/40 hover:text-white'
              }`}
              title="Real-Time Procedural Particle & Filament Engine"
            >
              <Cpu className="w-3 h-3" />
              <span className="hidden md:inline">Simulation</span>
            </button>
            <button
              onClick={() => setViewMode('split-view')}
              id="view-mode-split-btn"
              className={`flex items-center gap-1.5 px-3 py-1 text-[10px] uppercase tracking-[0.2em] rounded-sm transition-all ${
                viewMode === 'split-view'
                  ? 'bg-[#ef233c] text-white font-medium shadow-sm'
                  : 'text-white/40 hover:text-white'
              }`}
              title="Split Screen Comparison"
            >
              <Columns className="w-3 h-3" />
              <span className="hidden lg:inline">Split Compare</span>
            </button>
          </div>

          {/* Quick Copy button */}
          <button
            onClick={handleQuickCopy}
            id="header-quick-copy-btn"
            className="flex items-center gap-1.5 px-3.5 py-1.5 bg-transparent hover:bg-white/5 text-white/60 hover:text-white text-[10px] uppercase tracking-[0.2em] rounded-sm border border-white/20 hover:border-[#ef233c] transition-all"
            title="Copy banner directly to clipboard"
          >
            {copiedNotification ? (
              <>
                <Check className="w-3 h-3 text-[#ef233c]" />
                <span className="text-[#ef233c] font-medium">Copied</span>
              </>
            ) : (
              <>
                <Copy className="w-3 h-3" />
                <span className="hidden sm:inline">Copy PNG</span>
              </>
            )}
          </button>

          {/* Export button */}
          <button
            onClick={() => setIsExportOpen(true)}
            id="header-export-btn"
            className="flex items-center gap-2 px-5 py-2 bg-transparent hover:bg-[#ef233c] border border-white/20 hover:border-[#ef233c] text-white text-[10px] uppercase tracking-[0.2em] rounded-sm transition-all active:scale-[0.98]"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Export Graphic</span>
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-6 lg:px-12 py-8 space-y-8 z-10">
        {/* Banner Display Stage */}
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-1.5 h-1.5 rounded-full bg-[#ef233c] animate-ping" />
              <span className="text-[10px] font-mono uppercase tracking-[0.25em] text-white/50">
                {viewMode === 'rendered-3d'
                  ? '3D Studio Master Render // 1584×396 [5.9:1]'
                  : viewMode === 'procedural-live'
                  ? 'Active Procedural Filament Engine // 60 FPS'
                  : 'Comparative A/B Spectral Matrix'}
              </span>
            </div>

            <div className="flex items-center gap-4 text-[10px] font-mono tracking-widest text-white/30">
              <span>VOID: #050506</span>
              <span>&bull;</span>
              <span className="text-[#ef233c]">ACCENT: #EF233C</span>
            </div>
          </div>

          {/* Canvas Wrapper */}
          <div className="relative group rounded-sm overflow-hidden crimson-glow">
            <BannerCanvas
              ref={canvasHandleRef}
              config={config}
              viewMode={viewMode}
              mockup={mockup}
              guides={guides}
              splitPos={splitPos}
            />

            {/* Split view slider handle if split-view is active */}
            {viewMode === 'split-view' && (
              <div className="absolute bottom-3 left-1/2 -translate-x-1/2 bg-black/80 backdrop-blur-md px-4 py-1.5 rounded-sm border border-white/10 flex items-center gap-3 text-[10px] font-mono uppercase tracking-widest text-white/60">
                <span>3D Render</span>
                <input
                  type="range"
                  min="5"
                  max="95"
                  value={splitPos}
                  onChange={(e) => setSplitPos(parseInt(e.target.value))}
                  className="w-32 accent-[#ef233c] cursor-ew-resize"
                />
                <span>Simulation</span>
              </div>
            )}
          </div>

          {/* Quick Caption bar */}
          <div className="flex flex-wrap items-center justify-between gap-3 px-1 text-[10px] font-mono tracking-wider text-white/40">
            <div className="flex items-center gap-3">
              <span className="text-white/30 uppercase">Left 1/3 (0–528px):</span>
              <span className="text-white/70 font-light">Pure Void Negative Space</span>
              <span className="text-white/20">&bull;</span>
              <span className="text-white/30 uppercase">Position (1056px):</span>
              <span className="text-[#ef233c] font-light">Craggy Energy Sphere</span>
            </div>

            <button
              onClick={() => setIsExportOpen(true)}
              id="stage-download-native-btn"
              className="text-[#ef233c] hover:text-white uppercase tracking-[0.2em] flex items-center gap-1.5 transition-colors"
            >
              <Download className="w-3 h-3" />
              Download 1584×396 Master
            </button>
          </div>
        </section>

        {/* Elegant Dark Typographic Headline Banner */}
        <section className="border-t border-b border-white/5 py-8 flex flex-col md:flex-row justify-between items-start md:items-end gap-6">
          <div className="max-w-xl">
            <div className="text-[9px] uppercase tracking-[0.35em] text-[#ef233c] font-bold mb-2">
              Volumetric Visualization
            </div>
            <h2 className="text-3xl sm:text-4xl font-light tracking-tighter leading-tight text-white">
              Cinematic Rendering of <span className="italic text-[#ef233c]">Deep-Space</span> Phenomena
            </h2>
            <p className="text-xs text-white/50 leading-relaxed font-light mt-3">
              Capturing the organic density of craggy irregular silhouettes within a near-pure black vacuum. Studio-quality 3D assets rendered at 5.9:1 ultra-wide aspect ratio with a dedicated negative space safe zone.
            </p>
          </div>

          <div className="flex flex-col items-start md:items-end gap-3 shrink-0">
            <div className="text-left md:text-right">
              <div className="text-[9px] uppercase tracking-widest text-white/30 mb-0.5">Coordinates</div>
              <div className="text-xl font-mono tracking-tighter text-white">1584 &bull; 0396</div>
            </div>
            <button
              onClick={() => {
                setConfig((prev) => ({ ...prev, speed: prev.speed === 0 ? 1 : 0 }));
              }}
              className="px-6 py-2.5 bg-transparent border border-white/20 hover:border-[#ef233c] text-[10px] uppercase tracking-[0.2em] transition-colors rounded-sm text-white"
            >
              {config.speed === 0 ? 'Resume Simulation' : 'Freeze Simulation'}
            </button>
          </div>
        </section>

        {/* Platform Mockups Preview Selector */}
        <PlatformMockup
          currentMockup={mockup}
          onChangeMockup={setMockup}
        />

        {/* Composition Specifications & Dimension Metrics */}
        <SpecsOverlay
          guideMode={guides}
          onGuideChange={setGuides}
        />

        {/* Procedural Fine-Tuning Engine Controls */}
        <BannerControls
          config={config}
          onChange={setConfig}
          onReset={handleReset}
        />
      </main>

      {/* Footer */}
      <footer className="border-t border-white/5 bg-[#050506] px-6 lg:px-12 py-6 mt-auto flex flex-col sm:flex-row justify-between items-center gap-3 text-[9px] uppercase tracking-[0.2em] text-white/30 z-10">
        <div>&copy; Visual Systems Lab &bull; Aethel.Gard</div>
        <div className="flex gap-8">
          <span>Dynamic Crimson Accent: #ef233c</span>
          <span>Aspect Ratio 5.9:1 Optimized</span>
        </div>
      </footer>

      {/* High-Resolution Exporter Modal */}
      <ExportModal
        isOpen={isExportOpen}
        onClose={() => setIsExportOpen(false)}
        canvasHandle={canvasHandleRef.current}
      />
    </div>
  );
}
