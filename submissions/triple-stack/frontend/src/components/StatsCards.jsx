import React from 'react';
import { Ticket, Clock, CheckCircle2, Layers } from 'lucide-react';

const StatsCards = () => {
  const [data, setData] = React.useState(null);

  React.useEffect(() => {
    import('../lib/api').then(({ getAnalytics }) => {
      getAnalytics().then(res => setData(res)).catch(console.error);
    });
  }, []);

  const stats = [
    {
      title: "Open Tickets",
      value: data ? data.open.toString().padStart(2, '0') : "--",
      trend: "+12% vs last week",
      trendColor: "text-green-500",
      icon: <Ticket className="w-5 h-5 text-gray-400" />
    },
    {
      title: "Pending Response",
      value: data ? data.in_progress.toString().padStart(2, '0') : "--",
      trend: "+12% vs last week",
      trendColor: "text-red-500",
      icon: <Clock className="w-5 h-5 text-gray-400" />
    },
    {
      title: "Resolved Today",
      value: data ? data.resolved.toString().padStart(2, '0') : "--",
      trend: "+8% vs last week",
      trendColor: "text-green-500",
      icon: <CheckCircle2 className="w-5 h-5 text-gray-400" />
    },
    {
      title: "Overall Tickets",
      value: data ? data.total_tickets.toString().padStart(2, '0') : "--",
      trend: "+9% vs last week",
      trendColor: "text-green-500",
      icon: <Layers className="w-5 h-5 text-gray-400" />
    }
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 lg:gap-6">
      {stats.map((stat, idx) => (
        <div 
          key={idx} 
          className="bg-[#050505] border border-borderColor rounded-xl p-5 hover:border-gray-600 transition-colors flex flex-col relative overflow-hidden group"
        >
          {/* Top Title & Icon */}
          <div className="flex justify-between items-center mb-6">
            <h3 className="text-sm font-semibold text-white tracking-wide">{stat.title}</h3>
            <div className="w-8 h-8 rounded-lg border border-gray-800 flex items-center justify-center bg-black/50 group-hover:scale-110 transition-transform">
              {stat.icon}
            </div>
          </div>
          
          {/* Main Number */}
          <div className="text-4xl font-bold text-white tracking-tight mb-2">
            {stat.value}
          </div>
          
          {/* Trend */}
          <div className={`text-xs ${stat.trendColor} font-medium`}>
            {stat.trend}
          </div>
        </div>
      ))}
    </div>
  );
};

export default StatsCards;
