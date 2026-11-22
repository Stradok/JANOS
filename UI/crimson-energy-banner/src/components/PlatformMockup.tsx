import React from 'react';
import { PlatformMockupType } from '../types';
import { Linkedin, Twitter, Github, MessageSquare, Layout } from 'lucide-react';

interface PlatformMockupProps {
  currentMockup: PlatformMockupType;
  onChangeMockup: (type: PlatformMockupType) => void;
}

export const PlatformMockup: React.FC<PlatformMockupProps> = ({
  currentMockup,
  onChangeMockup,
}) => {
  return (
    <div className="bg-[#08080c] ring-1 ring-white/10 rounded-sm p-4 shadow-2xl">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-5 h-5 border border-[#ef233c] rotate-45 flex items-center justify-center shrink-0">
            <Layout className="w-2.5 h-2.5 text-[#ef233c] -rotate-45" />
          </div>
          <div>
            <span className="text-xs font-light uppercase tracking-[0.25em] text-white">Platform In-Context Simulation:</span>
            <span className="text-[10px] text-white/30 font-mono ml-2 hidden sm:inline">Avatar & Header Margins Validation</span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-1.5 bg-black/40 p-1 rounded-sm ring-1 ring-white/10">
          <button
            onClick={() => onChangeMockup('none')}
            id="mockup-btn-none"
            className={`px-3 py-1 text-[10px] uppercase tracking-[0.2em] font-mono rounded-sm transition-all ${
              currentMockup === 'none'
                ? 'bg-[#ef233c] text-white font-medium shadow-sm'
                : 'text-white/40 hover:text-white'
            }`}
          >
            Standalone
          </button>
          <button
            onClick={() => onChangeMockup('linkedin')}
            id="mockup-btn-linkedin"
            className={`flex items-center gap-1.5 px-3 py-1 text-[10px] uppercase tracking-[0.2em] font-mono rounded-sm transition-all ${
              currentMockup === 'linkedin'
                ? 'bg-[#ef233c] text-white font-medium shadow-sm'
                : 'text-white/40 hover:text-white'
            }`}
          >
            <Linkedin className="w-3 h-3" />
            <span>LinkedIn (1584×396)</span>
          </button>
          <button
            onClick={() => onChangeMockup('twitter')}
            id="mockup-btn-twitter"
            className={`flex items-center gap-1.5 px-3 py-1 text-[10px] uppercase tracking-[0.2em] font-mono rounded-sm transition-all ${
              currentMockup === 'twitter'
                ? 'bg-[#ef233c] text-white font-medium shadow-sm'
                : 'text-white/40 hover:text-white'
            }`}
          >
            <Twitter className="w-3 h-3" />
            <span>Twitter / X</span>
          </button>
          <button
            onClick={() => onChangeMockup('github')}
            id="mockup-btn-github"
            className={`flex items-center gap-1.5 px-3 py-1 text-[10px] uppercase tracking-[0.2em] font-mono rounded-sm transition-all ${
              currentMockup === 'github'
                ? 'bg-[#ef233c] text-white font-medium shadow-sm'
                : 'text-white/40 hover:text-white'
            }`}
          >
            <Github className="w-3 h-3" />
            <span>GitHub README</span>
          </button>
          <button
            onClick={() => onChangeMockup('discord')}
            id="mockup-btn-discord"
            className={`flex items-center gap-1.5 px-3 py-1 text-[10px] uppercase tracking-[0.2em] font-mono rounded-sm transition-all ${
              currentMockup === 'discord'
                ? 'bg-[#ef233c] text-white font-medium shadow-sm'
                : 'text-white/40 hover:text-white'
            }`}
          >
            <MessageSquare className="w-3 h-3" />
            <span>Discord</span>
          </button>
        </div>
      </div>
    </div>
  );
};
