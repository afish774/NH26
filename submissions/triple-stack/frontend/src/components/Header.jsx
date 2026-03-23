import React from 'react';
import { Search, Bell, Plus } from 'lucide-react';

const Header = () => {
  return (
    <header className="flex items-start justify-between py-6 px-8 lg:px-10 border-b border-borderColor pt-10">
      <div>
        <h1 className="text-[28px] font-bold text-white tracking-tight">Dashboard Overview</h1>
        <p className="text-gray-400 text-[15px] mt-1">Welcome back. Here's what's happening today.</p>
      </div>

      <div className="flex items-center gap-4">
        {/* Search */}
        <div className="relative group">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 w-4 h-4" />
          <input 
            type="text" 
            placeholder="Search tickets and customers....." 
            className="w-[280px] bg-transparent border border-gray-800 rounded-full py-2.5 pl-10 pr-4 text-sm text-gray-300 focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand transition-all placeholder:text-gray-600"
          />
        </div>

        {/* Notifications */}
        <button className="p-2.5 border border-gray-800 rounded-full text-gray-400 hover:text-white hover:border-gray-600 transition-colors relative">
          <Bell className="w-[18px] h-[18px]" />
          {/* subtle dot if needed */}
          <span className="absolute top-2 right-2.5 w-1.5 h-1.5 bg-brandPink rounded-full hidden"></span>
        </button>

        {/* New Ticket */}
        <button className="bg-brand hover:brightness-110 text-black px-4 py-2.5 rounded-full font-semibold text-sm flex items-center gap-1.5 transition-all active:scale-95">
          <Plus className="w-[18px] h-[18px]" />
          New Ticket
        </button>
      </div>
    </header>
  );
};

export default Header;
