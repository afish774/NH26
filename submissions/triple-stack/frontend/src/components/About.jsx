import React from 'react';

export default function About() {
  return (
    <div className="max-w-3xl bg-cardBg border border-borderColor rounded-xl p-8 animate-in fade-in duration-500">
      <h2 className="text-2xl font-bold text-white mb-4">About NexDesk</h2>
      <p className="text-gray-400 leading-relaxed mb-6">
        NexDesk is an advanced AI-powered IT support operating system designed to automate ticket resolution, empower employees with accurate self-service, and provide deep analytics to agent managers.
      </p>
      
      <div className="space-y-6">
        <div>
          <h3 className="text-brand font-semibold mb-2">Version</h3>
          <p className="text-white">v1.2.0 (Stable release)</p>
        </div>

        <div>
          <h3 className="text-brand font-semibold mb-2">Core Technologies</h3>
          <ul className="list-disc pl-5 space-y-2 text-gray-300">
            <li>React 18 & Vite</li>
            <li>Tailwind CSS Custom Design System</li>
            <li>Zustand State Management</li>
            <li>Recharts Data Visualization</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
