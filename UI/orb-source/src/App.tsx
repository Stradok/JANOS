import React, { useState, useEffect, useCallback } from 'react';
import { OrbSettings } from './types';
import { FragmentedOrbCanvas } from './components/FragmentedOrbCanvas';
import { CinematicOverlay } from './components/CinematicOverlay';
import { audioDrone } from './utils/audioDrone';

export default function App() {
  const [settings, setSettings] = useState<OrbSettings>({
    expansionSpeed: 0.55, // Slow, deliberate, weighty
    autoPushIn: true,
    manualScrub: false,
    scrubProgress: 0,
    particleDensity: 2800,
    shardCount: 48,
    glowIntensity: 1.8,
    theme: 'crimson',
    cameraMode: 'cinematic_push',
    audioEnabled: false,
    showHud: true,
    bloomAmount: 1.4,
  });

  const [currentPhase, setCurrentPhase] = useState<number>(0);
  const [isAssembled, setIsAssembled] = useState<boolean>(true);

  // Keyboard shortcut listener for cinema experience
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return;
      }
      if (e.code === 'Space') {
        e.preventDefault();
        setSettings((prev) => ({
          ...prev,
          manualScrub: !prev.manualScrub,
          scrubProgress: currentPhase,
        }));
      } else if (e.key.toLowerCase() === 'm') {
        if (settings.audioEnabled) {
          audioDrone.stop();
          setSettings((prev) => ({ ...prev, audioEnabled: false }));
        } else {
          audioDrone.start();
          setSettings((prev) => ({ ...prev, audioEnabled: true }));
        }
      } else if (e.key.toLowerCase() === 'h') {
        setSettings((prev) => ({ ...prev, showHud: !prev.showHud }));
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [settings.audioEnabled, currentPhase]);

  const handlePhaseChange = useCallback((phase: number, assembled: boolean) => {
    setCurrentPhase(phase);
    setIsAssembled(assembled);
  }, []);

  return (
    <main
      id="fragmented-orb-app"
      className="relative w-screen h-screen overflow-hidden bg-black flex items-center justify-center select-none"
    >
      {/* 3D WebGL Fragmented Orb Scene */}
      <FragmentedOrbCanvas
        settings={settings}
        onPhaseChange={handlePhaseChange}
      />

      {/* Cinematic UI Overlay */}
      {settings.showHud && (
        <CinematicOverlay
          settings={settings}
          onUpdateSettings={setSettings}
          currentPhase={currentPhase}
          isAssembled={isAssembled}
        />
      )}
    </main>
  );
}
