import React, { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import { TrendingDown, Clock, CheckCircle, AlertTriangle } from 'lucide-react';

const COLORS = ['#7dd3fc', '#ff007f', '#10b981', '#f59e0b', '#ef4444'];

export default function Analysis() {
  const [data, setData] = useState(null);

  useEffect(() => {
    import('../lib/api').then(({ getAnalytics }) => {
      getAnalytics().then(res => {
        // Capitalize priorities for the chart
        if (res.by_priority) {
          res.by_priority = res.by_priority.map(p => ({
            ...p,
            priority: p.priority.charAt(0).toUpperCase() + p.priority.slice(1)
          }));
        }
        setData(res);
      }).catch(e => console.error(e));
    });
  }, []);

  if (!data) return <div className="p-10 text-center text-gray-400">Loading analysis data...</div>;

  const metrics = [
    { label: 'Total Tickets', value: data.total_tickets, icon: <Clock size={22} className="text-brand" /> },
    { label: 'AI Deflection Rate', value: `${data.deflection_rate}%`, icon: <TrendingDown size={22} className="text-green-400" />, highlight: true },
    { label: 'Resolved', value: data.resolved, icon: <CheckCircle size={22} className="text-blue-400" /> },
    { label: 'SLA Breaches', value: data.sla_breached, icon: <AlertTriangle size={22} className="text-red-400" /> },
  ];

  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-[#111] border border-borderColor p-3 rounded-lg shadow-xl outline-none text-white text-sm">
          <p className="font-semibold mb-1 text-gray-200">{label || payload[0].name}</p>
          <p className="text-brand flex items-center gap-2">Count: <span className="font-bold text-white">{payload[0].value}</span></p>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-500 max-w-7xl mx-auto">
      {/* Metric Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {metrics.map((m, i) => (
          <div key={i} className="bg-cardBg border border-borderColor rounded-xl p-6 hover:border-gray-600 transition-colors">
            <div className="flex items-center justify-between mb-5">
              <span className="text-sm text-gray-400 font-medium">{m.label}</span>
              <div className="p-2.5 bg-black/50 rounded-lg border border-borderColor shadow-inner">{m.icon}</div>
            </div>
            <p className={`text-4xl font-bold tracking-tight ${m.highlight ? 'text-green-400' : 'text-white'}`}>
              {m.value}
            </p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Category Bar Chart */}
        <div className="bg-cardBg rounded-xl border border-borderColor p-6 hover:border-gray-700 transition-colors">
          <h3 className="text-base font-bold text-white mb-6">Tickets by Category</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={data.by_category} barSize={36}>
              <XAxis dataKey="category" tick={{ fill: '#8b949e', fontSize: 13 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: '#8b949e', fontSize: 13 }} axisLine={false} tickLine={false} />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: '#222' }} />
              <Bar dataKey="count" fill="#7dd3fc" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Priority Pie Chart */}
        <div className="bg-cardBg rounded-xl border border-borderColor p-6 hover:border-gray-700 transition-colors">
          <h3 className="text-base font-bold text-white mb-6">Tickets by Priority</h3>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={data.by_priority}
                dataKey="count"
                nameKey="priority"
                cx="50%"
                cy="50%"
                innerRadius={65}
                outerRadius={100}
                stroke="#09090b"
                strokeWidth={3}
                label={({ priority, percent }) => `${priority} ${(percent * 100).toFixed(0)}%`}
                labelLine={{ stroke: '#444' }}
              >
                {data.by_priority.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip content={<CustomTooltip />} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Deflection Callout */}
      <div className="bg-brand/10 border border-brand/20 rounded-xl p-6 flex items-start gap-4 shadow-lg shadow-brand/5">
        <div className="p-3 bg-brand/20 rounded-full text-brand shadow-inner flex-shrink-0"><CheckCircle size={24} /></div>
        <div>
          <h4 className="text-white font-bold mb-2">AI Deflection Impact</h4>
          <p className="text-[15px] text-gray-300 leading-relaxed">
            NexDesk AI successfully deflected <span className="text-brand font-bold">{data.total_deflected} tickets</span> this session — saving approximately <span className="text-green-400 font-bold">{Math.round(data.total_deflected * 0.5)} hours</span> of dedicated agent processing time.
          </p>
        </div>
      </div>
    </div>
  );
}
