import React, { useEffect, useRef, forwardRef, useImperativeHandle } from 'react';
import { BannerConfig, ViewMode, PlatformMockupType, AspectGuideMode } from '../types';

// Asset generated image
import generatedBannerUrl from '../assets/images/crimson_energy_banner_1787419193716.jpg';

export interface BannerCanvasHandle {
  exportImage: (scale: number) => string;
  getCanvasElement: () => HTMLCanvasElement | null;
}

interface BannerCanvasProps {
  config: BannerConfig;
  viewMode: ViewMode;
  mockup: PlatformMockupType;
  guides: AspectGuideMode;
  splitPos?: number; // 0 to 100 for split-view comparison
}

export const BannerCanvas = forwardRef<BannerCanvasHandle, BannerCanvasProps>(
  ({ config, viewMode, mockup, guides, splitPos = 50 }, ref) => {
    const canvasRef = useRef<HTMLCanvasElement | null>(null);
    const animFrameRef = useRef<number | null>(null);
    const imgRef = useRef<HTMLImageElement | null>(null);
    const timeRef = useRef<number>(0);

    // Preload generated image
    useEffect(() => {
      const img = new Image();
      img.src = generatedBannerUrl;
      img.referrerPolicy = 'no-referrer';
      img.onload = () => {
        imgRef.current = img;
      };
    }, []);

    // Method to export high-res PNG at scale
    useImperativeHandle(ref, () => ({
      exportImage: (scale: number = 1) => {
        const width = 1584 * scale;
        const height = 396 * scale;
        const offCanvas = document.createElement('canvas');
        offCanvas.width = width;
        offCanvas.height = height;
        const ctx = offCanvas.getContext('2d');
        if (!ctx) return '';

        // Render at target scale
        renderFrame(ctx, width, height, scale, timeRef.current, false);
        return offCanvas.toDataURL('image/png');
      },
      getCanvasElement: () => canvasRef.current,
    }));

    // Rendering algorithm
    const renderFrame = (
      ctx: CanvasRenderingContext2D,
      width: number,
      height: number,
      scale: number,
      time: number,
      includeGuides: boolean
    ) => {
      ctx.save();
      ctx.clearRect(0, 0, width, height);

      const targetX = config.sphereX * width;
      const targetY = config.sphereY * height;
      const radius = config.sphereRadius * scale;

      const drawProcedural = (clipRect?: { x: number; y: number; w: number; h: number }) => {
        ctx.save();
        if (clipRect) {
          ctx.beginPath();
          ctx.rect(clipRect.x, clipRect.y, clipRect.w, clipRect.h);
          ctx.clip();
        }

        // 1. Base void background
        ctx.fillStyle = config.backgroundColor || '#050506';
        ctx.fillRect(0, 0, width, height);

        // 2. Soft volumetric glow from sphere bleeding outward
        const glowRad = config.volumetricGlowRadius * scale * 2.2;
        const glowGrad = ctx.createRadialGradient(targetX, targetY, 0, targetX, targetY, glowRad);
        glowGrad.addColorStop(0, 'rgba(239, 35, 60, 0.42)');
        glowGrad.addColorStop(0.2, 'rgba(239, 35, 60, 0.22)');
        glowGrad.addColorStop(0.45, 'rgba(180, 15, 35, 0.08)');
        glowGrad.addColorStop(0.7, 'rgba(80, 5, 15, 0.025)');
        glowGrad.addColorStop(1, 'rgba(5, 5, 6, 0)');

        ctx.fillStyle = glowGrad;
        ctx.fillRect(0, 0, width, height);

        // 3. Fine atmospheric particle dust
        const particleCount = config.particleDustCount;
        for (let i = 0; i < particleCount; i++) {
          const pseudoRand = Math.sin(i * 997.13 + config.seed) * 10000;
          const px = ((pseudoRand - Math.floor(pseudoRand)) * width + Math.sin(time * 0.2 + i) * 8 * scale) % width;
          const py = (((pseudoRand * 13.7) % 1) * height + Math.cos(time * 0.15 + i) * 6 * scale) % height;

          // Distance to sphere
          const dx = px - targetX;
          const dy = py - targetY;
          const dist = Math.sqrt(dx * dx + dy * dy);

          // Particles are denser and brighter closer to sphere
          const falloff = Math.max(0, 1 - dist / (width * 0.6));
          const opacity = (0.15 + falloff * 0.75) * (0.4 + 0.6 * Math.sin(time * 0.8 + i));
          const pSize = (0.5 + falloff * 1.5) * scale;

          ctx.fillStyle = `rgba(239, 35, 60, ${opacity.toFixed(3)})`;
          ctx.beginPath();
          ctx.arc(px, py, pSize, 0, Math.PI * 2);
          ctx.fill();
        }

        // 4. Energy-web sphere filaments & craggy lattice
        const nodesCount = Math.floor(config.filamentDensity * 1.5);
        const nodes: { x: number; y: number; z: number; crag: number }[] = [];

        for (let i = 0; i < nodesCount; i++) {
          const theta = ((i * 137.5) * Math.PI) / 180;
          const phi = Math.acos(1 - (2 * (i + 0.5)) / nodesCount);

          // Craggy irregular distortion
          const noise =
            Math.sin(theta * 4 + time * config.filamentTurbulence * 1.5 + config.seed) *
            Math.cos(phi * 3 + time * 1.2) *
            config.cragginess *
            0.35;

          const r = radius * (1 + noise);
          const nx = r * Math.sin(phi) * Math.cos(theta + time * 0.4 * config.speed);
          const ny = r * Math.cos(phi);
          const nz = r * Math.sin(phi) * Math.sin(theta + time * 0.4 * config.speed);

          nodes.push({
            x: targetX + nx,
            y: targetY + ny,
            z: nz,
            crag: noise,
          });
        }

        // Connect adjacent nodes with crimson filaments
        ctx.lineWidth = 1.0 * scale;
        for (let i = 0; i < nodes.length; i++) {
          for (let j = i + 1; j < nodes.length; j++) {
            const n1 = nodes[i];
            const n2 = nodes[j];
            const dx = n1.x - n2.x;
            const dy = n1.y - n2.y;
            const d = Math.sqrt(dx * dx + dy * dy);

            if (d < radius * 0.55) {
              const alpha = (1 - d / (radius * 0.55)) * 0.55;
              const depthShade = ((n1.z + n2.z) / (radius * 2) + 1) * 0.5; // depth cue
              ctx.strokeStyle = `rgba(239, 35, 60, ${(alpha * depthShade).toFixed(3)})`;
              ctx.beginPath();
              ctx.moveTo(n1.x, n1.y);
              ctx.lineTo(n2.x, n2.y);
              ctx.stroke();
            }
          }
        }

        // 5. Long chaotic strands sweeping outward like sparks
        const sparkCount = config.sparkCount;
        for (let s = 0; s < sparkCount; s++) {
          const sAngle = (s * (Math.PI * 2 / sparkCount)) + Math.sin(time * 0.5 + s) * 0.4;
          const sLength = (config.sparkLength + Math.sin(time * 2.5 + s * 3) * 35) * scale;
          
          const startX = targetX + Math.cos(sAngle) * (radius * 0.7);
          const startY = targetY + Math.sin(sAngle) * (radius * 0.7);

          const ctrl1X = startX + Math.cos(sAngle + 0.3) * (sLength * 0.4) + Math.sin(time * 3 + s) * 20 * scale;
          const ctrl1Y = startY + Math.sin(sAngle + 0.3) * (sLength * 0.4) + Math.cos(time * 3 + s) * 20 * scale;

          const endX = startX + Math.cos(sAngle + 0.7) * sLength;
          const endY = startY + Math.sin(sAngle + 0.7) * sLength;

          const sparkAlpha = (0.25 + 0.5 * Math.sin(time * 4 + s * 7)) * Math.min(1, config.coreIntensity);

          // Filament line
          ctx.strokeStyle = `rgba(239, 35, 60, ${sparkAlpha.toFixed(3)})`;
          ctx.lineWidth = (0.8 + 0.6 * Math.sin(s)) * scale;
          ctx.beginPath();
          ctx.moveTo(startX, startY);
          ctx.quadraticCurveTo(ctrl1X, ctrl1Y, endX, endY);
          ctx.stroke();

          // Spark tip point
          ctx.fillStyle = `rgba(255, 230, 235, ${(sparkAlpha * 0.9).toFixed(3)})`;
          ctx.beginPath();
          ctx.arc(endX, endY, 1.2 * scale, 0, Math.PI * 2);
          ctx.fill();
        }

        // 6. Mid-red organic outer core body
        const outerGrad = ctx.createRadialGradient(targetX, targetY, radius * 0.2, targetX, targetY, radius * 1.05);
        outerGrad.addColorStop(0, 'rgba(239, 35, 60, 0.95)');
        outerGrad.addColorStop(0.4, 'rgba(200, 25, 45, 0.75)');
        outerGrad.addColorStop(0.75, 'rgba(120, 10, 25, 0.4)');
        outerGrad.addColorStop(1, 'rgba(20, 2, 5, 0)');

        ctx.fillStyle = outerGrad;
        ctx.beginPath();
        ctx.arc(targetX, targetY, radius * 1.05, 0, Math.PI * 2);
        ctx.fill();

        // 7. White-hot core bleeding through mid-red to dark edge
        const coreRad = radius * 0.45 * config.coreIntensity;
        const coreGrad = ctx.createRadialGradient(targetX, targetY, 0, targetX, targetY, coreRad);
        coreGrad.addColorStop(0, '#ffffff');
        coreGrad.addColorStop(0.18, '#fff0f2');
        coreGrad.addColorStop(0.4, '#ef233c');
        coreGrad.addColorStop(0.75, 'rgba(239, 35, 60, 0.6)');
        coreGrad.addColorStop(1, 'rgba(239, 35, 60, 0)');

        ctx.fillStyle = coreGrad;
        ctx.beginPath();
        ctx.arc(targetX, targetY, coreRad, 0, Math.PI * 2);
        ctx.fill();

        // High intensity center flare
        const flareRad = coreRad * 0.3;
        const flareGrad = ctx.createRadialGradient(targetX, targetY, 0, targetX, targetY, flareRad);
        flareGrad.addColorStop(0, 'rgba(255, 255, 255, 1)');
        flareGrad.addColorStop(0.5, 'rgba(255, 240, 245, 0.85)');
        flareGrad.addColorStop(1, 'rgba(255, 255, 255, 0)');
        ctx.fillStyle = flareGrad;
        ctx.beginPath();
        ctx.arc(targetX, targetY, flareRad, 0, Math.PI * 2);
        ctx.fill();

        ctx.restore();
      };

      const drawRendered3D = (clipRect?: { x: number; y: number; w: number; h: number }) => {
        ctx.save();
        if (clipRect) {
          ctx.beginPath();
          ctx.rect(clipRect.x, clipRect.y, clipRect.w, clipRect.h);
          ctx.clip();
        }

        if (imgRef.current && imgRef.current.complete) {
          // Fill background first
          ctx.fillStyle = '#050506';
          ctx.fillRect(0, 0, width, height);

          // Cover fit preserving aspect ratio
          const img = imgRef.current;
          const imgAspect = img.width / img.height;
          const canvasAspect = width / height;

          let renderW = width;
          let renderH = height;
          let offsetX = 0;
          let offsetY = 0;

          if (imgAspect > canvasAspect) {
            renderH = height;
            renderW = height * imgAspect;
            offsetX = -(renderW - width) * 0.6; // keep sphere well framed
          } else {
            renderW = width;
            renderH = width / imgAspect;
            offsetY = -(renderH - height) * 0.5;
          }

          ctx.drawImage(img, offsetX, offsetY, renderW, renderH);

          // Add soft subtle gradient on the far-left to ensure pure 100% negative space void
          const leftVoid = ctx.createLinearGradient(0, 0, width * 0.35, 0);
          leftVoid.addColorStop(0, 'rgba(5, 5, 6, 0.9)');
          leftVoid.addColorStop(0.7, 'rgba(5, 5, 6, 0.4)');
          leftVoid.addColorStop(1, 'rgba(5, 5, 6, 0)');
          ctx.fillStyle = leftVoid;
          ctx.fillRect(0, 0, width * 0.35, height);
        } else {
          // Fallback procedural while image loads
          drawProcedural(clipRect);
        }
        ctx.restore();
      };

      // Handle View Modes
      if (viewMode === 'rendered-3d') {
        drawRendered3D();
      } else if (viewMode === 'procedural-live') {
        drawProcedural();
      } else if (viewMode === 'split-view') {
        const splitX = (splitPos / 100) * width;
        // Left side: Rendered 3D Artwork
        drawRendered3D({ x: 0, y: 0, w: splitX, h: height });
        // Right side: Procedural Live Engine
        drawProcedural({ x: splitX, y: 0, w: width - splitX, h: height });

        // Divider line
        ctx.strokeStyle = '#ef233c';
        ctx.lineWidth = 2 * scale;
        ctx.beginPath();
        ctx.moveTo(splitX, 0);
        ctx.lineTo(splitX, height);
        ctx.stroke();

        // Handle knob
        ctx.fillStyle = '#ef233c';
        ctx.beginPath();
        ctx.arc(splitX, height / 2, 8 * scale, 0, Math.PI * 2);
        ctx.fill();
      }

      // Draw composition guides if requested
      if (includeGuides && guides !== 'none') {
        ctx.save();

        if (guides === 'composition-grid' || guides === 'all') {
          // 1. One-Third Negative Space Marker (528px at 1584w)
          const oneThirdX = width / 3;
          ctx.strokeStyle = 'rgba(239, 35, 60, 0.4)';
          ctx.setLineDash([6 * scale, 6 * scale]);
          ctx.lineWidth = 1 * scale;
          ctx.beginPath();
          ctx.moveTo(oneThirdX, 0);
          ctx.lineTo(oneThirdX, height);
          ctx.stroke();

          // 2. Two-Thirds Target Center (1056px at 1584w)
          const twoThirdsX = (width * 2) / 3;
          ctx.strokeStyle = 'rgba(255, 255, 255, 0.5)';
          ctx.beginPath();
          ctx.moveTo(twoThirdsX, 0);
          ctx.lineTo(twoThirdsX, height);
          ctx.stroke();

          // Horizontal Centerline
          ctx.strokeStyle = 'rgba(239, 35, 60, 0.25)';
          ctx.beginPath();
          ctx.moveTo(0, height / 2);
          ctx.lineTo(width, height / 2);
          ctx.stroke();

          ctx.setLineDash([]);
        }

        if (guides === 'safety-margins' || guides === 'all') {
          // 200px Left safety margin (no vital elements)
          const safety200px = (200 / 1584) * width;
          ctx.fillStyle = 'rgba(239, 35, 60, 0.08)';
          ctx.fillRect(0, 0, safety200px, height);

          ctx.strokeStyle = 'rgba(239, 35, 60, 0.7)';
          ctx.lineWidth = 1.5 * scale;
          ctx.setLineDash([4 * scale, 4 * scale]);
          ctx.beginPath();
          ctx.moveTo(safety200px, 0);
          ctx.lineTo(safety200px, height);
          ctx.stroke();
          ctx.setLineDash([]);
        }

        ctx.restore();
      }

      ctx.restore();
    };

    // Animation Loop for procedural canvas
    useEffect(() => {
      const canvas = canvasRef.current;
      if (!canvas) return;

      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      let running = true;

      const loop = () => {
        if (!running) return;
        timeRef.current += 0.016 * config.speed;
        renderFrame(ctx, 1584, 396, 1, timeRef.current, true);
        animFrameRef.current = requestAnimationFrame(loop);
      };

      loop();

      return () => {
        running = false;
        if (animFrameRef.current) {
          cancelAnimationFrame(animFrameRef.current);
        }
      };
    }, [config, viewMode, guides, splitPos]);

    return (
      <div id="banner-canvas-container" className="relative w-full overflow-hidden rounded-sm bg-[#050506] ring-1 ring-white/10 shadow-2xl transition-all duration-300">
        {/* Ambient subtle glow background */}
        <div className="absolute inset-0 elegant-radial-glow pointer-events-none z-0" />

        {/* Banner aspect ratio container: 1584 / 396 = 4:1 / 5.9:1 ultra-wide */}
        <div className="relative w-full z-10" style={{ paddingBottom: '25%' }}>
          <canvas
            ref={canvasRef}
            id="banner-native-canvas"
            width={1584}
            height={396}
            className="absolute inset-0 w-full h-full object-cover block"
          />

          {/* Elegant Anomaly Reference Badge (Bottom Left) */}
          <div className="absolute bottom-4 left-6 hidden sm:flex flex-col gap-0.5 pointer-events-none select-none z-20">
            <span className="text-[8px] uppercase tracking-[0.3em] text-[#ef233c] font-bold">Anomaly Reference</span>
            <span className="text-[10px] font-mono text-white/30 tracking-wider">REF_05.9.1_VVOID</span>
          </div>

          {/* Social Platform Mockup Overlays */}
          {mockup === 'linkedin' && (
            <div className="absolute inset-0 pointer-events-none flex flex-col justify-end p-6 md:p-8 bg-gradient-to-t from-black/70 via-transparent to-transparent z-20">
              <div className="flex items-end gap-4">
                {/* Profile avatar positioned in the safe negative space on bottom-left (<200px) */}
                <div className="w-16 h-16 md:w-24 md:h-24 rounded-full border-2 border-white/20 bg-[#0a0a0e] shadow-2xl flex items-center justify-center -mb-8 overflow-hidden">
                  <div className="w-full h-full bg-gradient-to-tr from-[#08080a] to-[#15151d] flex items-center justify-center text-[10px] font-mono tracking-widest text-white/40">
                    AVATAR
                  </div>
                </div>
                <div className="hidden sm:block pb-1 text-left">
                  <div className="text-white text-xs md:text-sm font-light tracking-widest uppercase drop-shadow">
                    Safe Left-Third Zone
                  </div>
                  <div className="text-white/40 text-[10px] font-mono">
                    200px avatar margin respected
                  </div>
                </div>
              </div>
            </div>
          )}

          {mockup === 'twitter' && (
            <div className="absolute inset-0 pointer-events-none flex flex-col justify-end p-6 md:p-8 z-20">
              <div className="w-16 h-16 md:w-20 md:h-20 rounded-full border-2 border-white/20 bg-[#0c0c10] flex items-center justify-center -mb-6 shadow-xl">
                <span className="text-[9px] font-mono tracking-widest text-white/40">X AVATAR</span>
              </div>
            </div>
          )}

          {mockup === 'github' && (
            <div className="absolute inset-0 pointer-events-none border-b border-white/10 p-4 flex justify-between items-start z-20">
              <div className="px-2.5 py-1 bg-black/80 backdrop-blur-md rounded-sm text-[9px] font-mono uppercase tracking-[0.2em] text-white/50 border border-white/10">
                README.md Banner / 1584×396
              </div>
            </div>
          )}

          {mockup === 'discord' && (
            <div className="absolute inset-0 pointer-events-none p-4 flex items-end z-20">
              <div className="w-14 h-14 rounded-full bg-[#111116] border-2 border-white/20 flex items-center justify-center shadow-lg -mb-4">
                <span className="text-[8px] font-mono tracking-widest text-white/40">STATUS</span>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }
);
