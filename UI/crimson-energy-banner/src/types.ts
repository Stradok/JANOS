export interface BannerConfig {
  sphereX: number; // 0 to 1 (default 0.67 for 2/3 across frame)
  sphereY: number; // 0 to 1 (default 0.50)
  sphereRadius: number; // 40 to 180 (default 95)
  coreIntensity: number; // 0.5 to 2.0 (white hot glow)
  filamentDensity: number; // 20 to 120
  filamentTurbulence: number; // 0.1 to 3.0
  sparkCount: number; // 10 to 80
  sparkLength: number; // 40 to 220
  particleDustCount: number; // 100 to 1200
  volumetricGlowRadius: number; // 100 to 500
  cragginess: number; // 0.1 to 1.0 (irregular silhouette)
  accentColor: string; // default #ef233c
  backgroundColor: string; // default #050506
  speed: number; // 0 (paused) to 2
  seed: number;
}

export type ViewMode = 'rendered-3d' | 'procedural-live' | 'split-view';
export type PlatformMockupType = 'none' | 'linkedin' | 'twitter' | 'github' | 'discord';
export type AspectGuideMode = 'none' | 'composition-grid' | 'safety-margins' | 'all';
