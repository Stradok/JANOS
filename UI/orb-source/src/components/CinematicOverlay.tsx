import React, { useState } from 'react';
import { OrbSettings, VisualTheme, CameraMode } from '../types';
import { THEMES } from '../utils/themes';
import { audioDrone } from '../utils/audioDrone';
import { 
  Play, 
  Pause, 
  Volume2, 
  VolumeX, 
  Maximize2, 
  Minimize2, 
  Eye, 
  EyeOff, 
  Sparkles, 
  Compass, 
  Sliders, 
  RotateCcw,
  Layers
} from 'lucide-react';

interface Props {
  settings: OrbSettings;
  onUpdateSettings: (updater: (prev: OrbSettings) => OrbSettings) => void;
  currentPhase: number;
  isAssembled: boolean;
}

export const CinematicOverlay: React.FC<Props> = ({
  settings,
  onUpdateSettings,
  currentPhase,
  isAssembled,
}) => {
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showSettingsDrawer, setShowSettingsDrawer] = useState(false);

  const toggleSound = () => {
    if (settings.audioEnabled) {
      audioDrone.stop();
      onUpdateSettings((prev) => ({ ...prev, audioEnabled: false }));
    } else {
      audioDrone.start();
      onUpdateSettings((prev) => ({ ...prev, audioEnabled: true }));
    }
  };

  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().then(() => setIsFullscreen(true)).catch(() => {});
    } else {
      document.exitFullscreen().then(() => setIsFullscreen(false)).catch(() => {});
    }
  };

  const toggleAutoPlay = () => {
    onUpdateSettings((prev) => ({
      ...prev,
      manualScrub: !prev.manualScrub,
      scrubProgress: currentPhase,
    }));
  };

  const currentTheme = THEMES[settings.theme];
  const phasePercent = Math.round(currentPhase * 100);

  return (
    <div id="cinematic-overlay-root" className="pointer-events-none absolute inset-0 flex flex-col justify-between p-4 md:p-7 z-10 text-zinc-100 font-sans select-none">
      {/* Top Header Bar */}
      <div className="flex items-center justify-between w-full">
        {/* Title & Status */}
        <div className="flex items-center gap-3">
          <div className="pointer-events-auto flex items-center gap-2.5 px-3.5 py-1.5 rounded-full bg-zinc-950/70 border border-zinc-800/80 backdrop-blur-md shadow-2xl">
            <span
              className="w-2.5 h-2.5 rounded-full animate-pulse"
              style={{ backgroundColor: currentTheme.glowColor, boxShadow: `0 0 10px ${currentTheme.glowColor}` }}
            />
            <span className="text-xs tracking-widest font-semibold text-zinc-200 uppercase">
              Fragmented Orb
            </span>
          </div>

          {/* Assembly State Badge */}
          <div className="hidden sm:flex items-center px-3 py-1 rounded-full bg-zinc-900/50 border border-zinc-800/50 text-[11px] font-mono text-zinc-400">
            {isAssembled ? (
              <span className="text-emerald-400 font-medium">LOCKED • FULLY ASSEMBLED</span>
            ) : (
              <span>DRIFT EXPANSION • {phasePercent}%</span>
            )}
          </div>
        </div>

        {/* Quick Action Controls */}
        <div className="pointer-events-auto flex items-center gap-2">
          {/* Ambient Audio Toggle */}
          <button
            id="btn-toggle-audio"
            onClick={toggleSound}
            title={settings.audioEnabled ? 'Mute Atmospheric Drone' : 'Unmute Atmospheric Drone'}
            className={`p-2.5 rounded-xl border transition-all duration-200 backdrop-blur-md ${
              settings.audioEnabled
                ? 'bg-red-950/40 border-red-500/50 text-red-300 shadow-[0_0_15px_rgba(255,40,60,0.3)]'
                : 'bg-zinc-950/70 border-zinc-800/80 text-zinc-400 hover:text-zinc-200 hover:border-zinc-700'
            }`}
          >
            {settings.audioEnabled ? <Volume2 size={16} /> : <VolumeX size={16} />}
          </button>

          {/* Quick Drawer Toggle */}
          <button
            id="btn-toggle-drawer"
            onClick={() => setShowSettingsDrawer(!showSettingsDrawer)}
            title="Customization Options"
            className={`p-2.5 rounded-xl border transition-all duration-200 backdrop-blur-md ${
              showSettingsDrawer
                ? 'bg-zinc-800 border-zinc-600 text-white'
                : 'bg-zinc-950/70 border-zinc-800/80 text-zinc-400 hover:text-zinc-200 hover:border-zinc-700'
            }`}
          >
            <Sliders size={16} />
          </button>

          {/* Fullscreen Toggle */}
          <button
            id="btn-toggle-fullscreen"
            onClick={toggleFullscreen}
            title="Toggle Fullscreen"
            className="p-2.5 rounded-xl bg-zinc-950/70 border border-zinc-800/80 text-zinc-400 hover:text-zinc-200 hover:border-zinc-700 backdrop-blur-md transition-all duration-200"
          >
            {isFullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
          </button>
        </div>
      </div>

      {/* Settings Drawer (Foldable Panel) */}
      {showSettingsDrawer && (
        <div
          id="settings-drawer-panel"
          className="pointer-events-auto self-end max-w-sm w-full bg-zinc-950/90 border border-zinc-800/90 rounded-2xl p-4.5 my-2 backdrop-blur-xl shadow-2xl space-y-4 transition-all duration-200"
        >
          {/* Theme Palette */}
          <div>
            <label className="text-[11px] uppercase tracking-wider font-semibold text-zinc-400 block mb-2">
              Core Plasma Spectrum
            </label>
            <div className="grid grid-cols-2 gap-2">
              {(Object.keys(THEMES) as VisualTheme[]).map((themeKey) => {
                const t = THEMES[themeKey];
                const isActive = settings.theme === themeKey;
                return (
                  <button
                    key={themeKey}
                    id={`btn-theme-${themeKey}`}
                    onClick={() => onUpdateSettings((prev) => ({ ...prev, theme: themeKey }))}
                    className={`flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium border transition-all ${
                      isActive
                        ? 'bg-zinc-800/90 border-zinc-600 text-white shadow-lg'
                        : 'bg-zinc-900/40 border-zinc-800/60 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900'
                    }`}
                  >
                    <span
                      className="w-3 h-3 rounded-full flex-shrink-0"
                      style={{ backgroundColor: t.glowColor }}
                    />
                    <span className="truncate">{t.name}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Camera Perspectives */}
          <div>
            <label className="text-[11px] uppercase tracking-wider font-semibold text-zinc-400 block mb-2">
              Camera Movement
            </label>
            <div className="grid grid-cols-2 gap-2">
              {[
                { id: 'cinematic_push', label: 'Cinematic Push-in', icon: Sparkles },
                { id: 'core_macro', label: 'Core Fissure Macro', icon: Layers },
                { id: 'free_orbit', label: 'Free 3D Orbit', icon: Compass },
                { id: 'wide_cinematic', label: 'Wide Cinema', icon: Eye },
              ].map((item) => {
                const Icon = item.icon;
                const isActive = settings.cameraMode === item.id;
                return (
                  <button
                    key={item.id}
                    id={`btn-camera-${item.id}`}
                    onClick={() => onUpdateSettings((prev) => ({ ...prev, cameraMode: item.id as CameraMode }))}
                    className={`flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-medium border transition-all ${
                      isActive
                        ? 'bg-zinc-800/90 border-zinc-600 text-white'
                        : 'bg-zinc-900/40 border-zinc-800/60 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900'
                    }`}
                  >
                    <Icon size={14} className={isActive ? 'text-red-400' : 'text-zinc-500'} />
                    <span className="truncate">{item.label}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Speed Presets */}
          <div>
            <label className="text-[11px] uppercase tracking-wider font-semibold text-zinc-400 block mb-2">
              Motion Weight & Cadence
            </label>
            <div className="flex items-center gap-1.5">
              {[
                { val: 0.35, label: '0.35x Weighty' },
                { val: 0.65, label: '0.65x Deliberate' },
                { val: 1.0, label: '1.0x Normal' },
                { val: 1.5, label: '1.5x Dynamic' },
              ].map((sp) => (
                <button
                  key={sp.val}
                  id={`btn-speed-${sp.val}`}
                  onClick={() => onUpdateSettings((prev) => ({ ...prev, expansionSpeed: sp.val }))}
                  className={`flex-1 py-1.5 text-[11px] rounded-lg border font-mono transition-all ${
                    Math.abs(settings.expansionSpeed - sp.val) < 0.05
                      ? 'bg-zinc-800 border-zinc-600 text-zinc-100 font-semibold'
                      : 'bg-zinc-900/40 border-zinc-800/60 text-zinc-400 hover:text-zinc-200'
                  }`}
                >
                  {sp.label.split(' ')[0]}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Bottom Main Navigation & Scrubber Bar */}
      <div className="pointer-events-auto flex flex-col items-center gap-3 w-full max-w-2xl mx-auto">
        {/* Interaction Hint */}
        <div className="flex items-center gap-4 text-[11px] font-mono text-zinc-500 tracking-wide">
          <span>DRAG TO ORBIT</span>
          <span>•</span>
          <span>SCROLL TO ZOOM</span>
          <span>•</span>
          <span>SEAMLESS DRIFT LOOP</span>
        </div>

        {/* Floating Master Control Capsule */}
        <div className="w-full bg-zinc-950/85 border border-zinc-800/90 rounded-2xl p-3 md:px-5 md:py-3.5 backdrop-blur-xl shadow-2xl flex flex-col sm:flex-row items-center gap-3.5">
          {/* Play / Manual Toggle */}
          <button
            id="btn-play-pause-loop"
            onClick={toggleAutoPlay}
            title={settings.manualScrub ? 'Resume Cinematic Auto-Loop' : 'Pause & Manual Scrub'}
            className="flex items-center justify-center w-9 h-9 rounded-xl bg-zinc-800/90 hover:bg-zinc-700 text-zinc-100 border border-zinc-700 transition-all flex-shrink-0"
          >
            {settings.manualScrub ? <Play size={16} className="ml-0.5" /> : <Pause size={16} />}
          </button>

          {/* Timeline / Drift Scrubber */}
          <div className="flex-1 w-full flex flex-col gap-1">
            <div className="flex items-center justify-between text-[11px] font-mono text-zinc-400">
              <span className="flex items-center gap-1.5">
                <RotateCcw size={11} className="text-zinc-500" />
                {settings.manualScrub ? 'MANUAL PHASE' : 'SEAMLESS LOOP'}
              </span>
              <span className="font-semibold text-zinc-200">{phasePercent}%</span>
            </div>

            <input
              id="input-orb-scrubber"
              type="range"
              min="0"
              max="1"
              step="0.005"
              value={settings.manualScrub ? settings.scrubProgress : currentPhase}
              onChange={(e) => {
                const val = parseFloat(e.target.value);
                onUpdateSettings((prev) => ({
                  ...prev,
                  manualScrub: true,
                  scrubProgress: val,
                }));
              }}
              className="w-full h-2 bg-zinc-800 rounded-lg appearance-none cursor-pointer accent-red-500 hover:accent-red-400 transition-all"
            />
          </div>

          {/* Mode Switcher pill */}
          <div className="flex items-center gap-1 bg-zinc-900/80 p-1 rounded-xl border border-zinc-800/80">
            <button
              id="btn-mode-push"
              onClick={() => onUpdateSettings((prev) => ({ ...prev, cameraMode: 'cinematic_push' }))}
              className={`px-2.5 py-1 text-xs rounded-lg font-medium transition-all ${
                settings.cameraMode === 'cinematic_push'
                  ? 'bg-zinc-800 text-white shadow-sm'
                  : 'text-zinc-400 hover:text-zinc-200'
              }`}
            >
              Push-in
            </button>
            <button
              id="btn-mode-orbit"
              onClick={() => onUpdateSettings((prev) => ({ ...prev, cameraMode: 'free_orbit' }))}
              className={`px-2.5 py-1 text-xs rounded-lg font-medium transition-all ${
                settings.cameraMode === 'free_orbit'
                  ? 'bg-zinc-800 text-white shadow-sm'
                  : 'text-zinc-400 hover:text-zinc-200'
              }`}
            >
              Free 3D
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
