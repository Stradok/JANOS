import React, { useState } from 'react';
import { Download, Copy, Check, X } from 'lucide-react';
import { BannerCanvasHandle } from './BannerCanvas';

interface ExportModalProps {
  isOpen: boolean;
  onClose: () => void;
  canvasHandle: BannerCanvasHandle | null;
}

export const ExportModal: React.FC<ExportModalProps> = ({
  isOpen,
  onClose,
  canvasHandle,
}) => {
  const [copied, setCopied] = useState(false);
  const [selectedScale, setSelectedScale] = useState<number>(1);
  const [exporting, setExporting] = useState(false);

  if (!isOpen) return null;

  const downloadBanner = (scale: number) => {
    if (!canvasHandle) return;
    setExporting(true);
    try {
      const dataUrl = canvasHandle.exportImage(scale);
      const link = document.createElement('a');
      const filename = `crimson-energy-banner-${1584 * scale}x${396 * scale}.png`;
      link.download = filename;
      link.href = dataUrl;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } finally {
      setExporting(false);
    }
  };

  const copyToClipboard = async () => {
    if (!canvasHandle) return;
    try {
      const dataUrl = canvasHandle.exportImage(1);
      const res = await fetch(dataUrl);
      const blob = await res.blob();
      await navigator.clipboard.write([
        new ClipboardItem({
          [blob.type]: blob,
        }),
      ]);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch (e) {
      console.error('Clipboard copy error:', e);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/85 backdrop-blur-md animate-fadeIn">
      <div className="relative w-full max-w-lg bg-[#08080c] ring-1 ring-white/10 rounded-sm p-6 shadow-2xl space-y-6 text-left">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/5 pb-4">
          <div className="flex items-center gap-3">
            <div className="w-5 h-5 border border-[#ef233c] rotate-45 flex items-center justify-center shrink-0">
              <Download className="w-2.5 h-2.5 text-[#ef233c] -rotate-45" />
            </div>
            <div>
              <h3 className="text-xs font-light uppercase tracking-[0.3em] text-white">Export Banner Graphic</h3>
              <p className="text-[10px] text-white/40 font-mono tracking-wider">Uncompressed 5.9:1 raster pipeline</p>
            </div>
          </div>

          <button
            onClick={onClose}
            id="close-export-modal-btn"
            className="w-7 h-7 rounded-sm bg-transparent hover:bg-white/10 border border-white/10 flex items-center justify-center text-white/60 hover:text-white transition-colors"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Resolution Selector */}
        <div className="space-y-3">
          <label className="text-[10px] font-mono uppercase tracking-[0.25em] text-white/50 block">
            Resolution Profile:
          </label>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <button
              onClick={() => setSelectedScale(1)}
              id="export-scale-1x-btn"
              className={`p-3.5 rounded-sm border text-left transition-all ${
                selectedScale === 1
                  ? 'border-[#ef233c] bg-[#ef233c]/10 text-white'
                  : 'border-white/10 bg-black/40 text-white/50 hover:border-white/20 hover:text-white'
              }`}
            >
              <div className="text-[11px] uppercase tracking-wider font-mono text-white">1x Standard</div>
              <div className="text-[10px] text-[#ef233c] font-mono mt-0.5">1584 × 396 px</div>
              <div className="text-[9px] text-white/30 mt-1 uppercase tracking-wider">Web & LinkedIn</div>
            </button>

            <button
              onClick={() => setSelectedScale(2)}
              id="export-scale-2x-btn"
              className={`p-3.5 rounded-sm border text-left transition-all ${
                selectedScale === 2
                  ? 'border-[#ef233c] bg-[#ef233c]/10 text-white'
                  : 'border-white/10 bg-black/40 text-white/50 hover:border-white/20 hover:text-white'
              }`}
            >
              <div className="text-[11px] uppercase tracking-wider font-mono text-white">2x Retina HD</div>
              <div className="text-[10px] text-[#ef233c] font-mono mt-0.5">3168 × 792 px</div>
              <div className="text-[9px] text-white/30 mt-1 uppercase tracking-wider">HiDPI & 4K</div>
            </button>

            <button
              onClick={() => setSelectedScale(3)}
              id="export-scale-3x-btn"
              className={`p-3.5 rounded-sm border text-left transition-all ${
                selectedScale === 3
                  ? 'border-[#ef233c] bg-[#ef233c]/10 text-white'
                  : 'border-white/10 bg-black/40 text-white/50 hover:border-white/20 hover:text-white'
              }`}
            >
              <div className="text-[11px] uppercase tracking-wider font-mono text-white">3x Master</div>
              <div className="text-[10px] text-[#ef233c] font-mono mt-0.5">4752 × 1188 px</div>
              <div className="text-[9px] text-white/30 mt-1 uppercase tracking-wider">Studio Archival</div>
            </button>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-col sm:flex-row items-center gap-3 pt-2">
          <button
            onClick={() => downloadBanner(selectedScale)}
            disabled={exporting}
            id="download-selected-png-btn"
            className="w-full sm:flex-1 flex items-center justify-center gap-2 py-3 px-4 bg-[#ef233c] hover:bg-[#d90429] text-white text-[10px] uppercase tracking-[0.2em] font-medium rounded-sm transition-all shadow-lg shadow-[#ef233c]/20 active:scale-[0.98] disabled:opacity-50"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Download {1584 * selectedScale}×{396 * selectedScale} PNG</span>
          </button>

          <button
            onClick={copyToClipboard}
            id="copy-to-clipboard-png-btn"
            className="w-full sm:w-auto flex items-center justify-center gap-2 py-3 px-4 bg-transparent hover:bg-white/5 text-white/80 hover:text-white text-[10px] uppercase tracking-[0.2em] font-medium rounded-sm border border-white/20 hover:border-[#ef233c] transition-colors"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-[#ef233c]" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copied ? 'Copied' : 'Copy PNG'}</span>
          </button>
        </div>
      </div>
    </div>
  );
};
