import React from 'react';
import { LayoutDashboard, Users, BarChart2, Info } from 'lucide-react';

const Sidebar = ({ currentTab, setCurrentTab }) => {
  const menuItems = [
    { name: 'Overview', icon: LayoutDashboard },
    { name: 'Connect', icon: Users },
    { name: 'Analysis', icon: BarChart2 },
    { name: 'About', icon: Info },
  ];

  return (
    <div className="w-64 h-full bg-[#030303] flex flex-col py-8 px-6 border-r border-borderColor shrink-0">
      <h1 className="text-xl font-bold text-white mb-10 tracking-wide text-center">NexdesK</h1>
      
      <nav className="flex flex-col gap-2">
        {menuItems.map((item, idx) => {
          const Icon = item.icon;
          const isActive = currentTab === item.name;
          
          return isActive ? (
            <div key={idx} className="flex items-center gap-3 px-4 py-3 bg-brand text-black rounded-xl font-medium cursor-pointer transition-transform hover:scale-[1.02]">
              <Icon size={20} className="fill-black/30" />
              <span>{item.name}</span>
            </div>
          ) : (
            <div 
              key={idx} 
              onClick={() => setCurrentTab(item.name)}
              className="flex items-center gap-3 px-4 py-3 text-gray-400 hover:text-white hover:bg-white/5 rounded-xl cursor-pointer transition-colors"
            >
              <Icon size={20} />
              <span className="font-medium text-[15px]">{item.name}</span>
            </div>
          );
        })}
      </nav>

      {/* User Profile at Bottom */}
      <div className="mt-auto pt-6 border-t border-borderColor/50">
        <div className="flex items-center gap-3 cursor-pointer group">
          <img src="https://ui-avatars.com/api/?name=Amal+SS&background=111&color=fff&rounded=true" alt="Avatar" className="w-10 h-10 rounded-full border border-gray-800 shrink-0" />
          <div className="flex-1 overflow-hidden">
            <p className="text-[13px] font-bold text-white truncate">Amal SS</p>
            <p className="text-[11px] text-gray-500 truncate mt-0.5">Lead Operator</p>
          </div>
          <svg className="w-[18px] h-[18px] text-gray-500 group-hover:text-white transition-colors shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
          </svg>
        </div>
      </div>
    </div>
  );
};

export default Sidebar;
