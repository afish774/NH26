import React, { useState } from 'react';
import { Eye, Edit2, MoreVertical } from 'lucide-react';

const TicketTable = () => {
  const [mockTickets, setMockTickets] = useState([]);
  const [loading, setLoading] = useState(true);

  React.useEffect(() => {
    import('../lib/api').then(({ getTickets }) => {
      getTickets().then(data => {
        const formatted = data.map(t => ({
          id: t.id.substring(0, 8).toUpperCase(),
          subject: t.title,
          time: t.created_at ? new Date(t.created_at).toLocaleString() : 'Just now',
          customer: t.user_id || 'System User',
          status: t.status ? t.status.replace('_', ' ') : 'Open',
          priority: t.priority ? t.priority.charAt(0).toUpperCase() + t.priority.slice(1) : 'Medium'
        }));
        setMockTickets(formatted);
        setLoading(false);
      }).catch(e => {
        console.error('Failed to load tickets', e);
        setLoading(false);
      });
    });
  }, []);

  const getPriorityStyle = (priority) => {
    switch (priority) {
      case 'Low': return { color: 'text-blue-500', dot: 'bg-blue-500' };
      case 'High': return { color: 'text-red-500', dot: 'bg-red-500' };
      case 'Medium': return { color: 'text-orange-500', dot: 'bg-orange-500' };
      default: return { color: 'text-gray-500', dot: 'bg-gray-500' };
    }
  };

  return (
    <div className="w-full overflow-x-auto">
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="border-b border-borderColor text-gray-500 text-xs font-semibold tracking-wider">
            <th className="pb-4 pt-2 pr-6 uppercase whitespace-nowrap">Ticket ID</th>
            <th className="pb-4 pt-2 px-6 uppercase whitespace-nowrap">Subject</th>
            <th className="pb-4 pt-2 px-6 uppercase whitespace-nowrap">Customer</th>
            <th className="pb-4 pt-2 px-6 uppercase whitespace-nowrap">Status</th>
            <th className="pb-4 pt-2 px-6 uppercase whitespace-nowrap">Priority</th>
            <th className="pb-4 pt-2 pl-6 uppercase whitespace-nowrap text-right">Actions</th>
          </tr>
        </thead>
        <tbody className="text-sm">
          {mockTickets.map((ticket, idx) => {
            const priorityStyle = getPriorityStyle(ticket.priority);
            
            return (
              <tr 
                key={idx} 
                className="border-b border-borderColor/50 hover:bg-white/[0.02] transition-colors group"
              >
                {/* ID */}
                <td className="py-4 pr-6 font-medium text-brand whitespace-nowrap">
                  {ticket.id}
                </td>
                
                {/* Subject */}
                <td className="py-4 px-6 min-w-[280px]">
                  <div className="font-medium text-gray-200">{ticket.subject}</div>
                  <div className="text-gray-500 text-xs mt-1">{ticket.time}</div>
                </td>
                
                {/* Customer */}
                <td className="py-4 px-6 whitespace-nowrap">
                  <div className="flex items-center gap-3">
                    <div className="w-7 h-7 rounded-full bg-gray-200" />
                    <span className="text-gray-400 font-medium">{ticket.customer}</span>
                  </div>
                </td>
                
                {/* Status */}
                <td className="py-4 px-6 whitespace-nowrap">
                  <span className="inline-flex items-center px-3 py-1 rounded-md text-xs font-medium bg-green-900/20 text-green-500 border border-green-800/50">
                    {ticket.status}
                  </span>
                </td>
                
                {/* Priority */}
                <td className="py-4 px-6 whitespace-nowrap cursor-pointer relative">
                  <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium bg-[#1a1a1a] border border-[#27272a] hover:border-gray-600 transition-colors">
                    <span className={`w-2 h-2 rounded-full ${priorityStyle.dot}`} />
                    <span className={priorityStyle.color}>{ticket.priority}</span>
                  </span>
                  
                  {/* Tooltip Simulation on hover on the 7th item like the design */}
                  {idx === 6 && (
                    <div className="absolute top-1/2 left-full -translate-y-1/2 ml-2 opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap z-10 hidden lg:block">
                       <div className="bg-brandPink text-white text-xs font-bold px-3 py-1.5 rounded">
                         Abhinav Sankar
                       </div>
                       {/* Arrow part of tooltip */}
                       <div className="absolute top-1/2 right-full -translate-y-1/2 border-[5px] border-transparent border-r-brandPink" />
                    </div>
                  )}
                </td>
                
                {/* Actions */}
                <td className="py-4 pl-6 text-right whitespace-nowrap align-middle">
                  <div className="flex items-center justify-end gap-3 text-gray-500">
                    <button className="hover:text-white transition-colors p-1" title="View">
                      <Eye size={18} />
                    </button>
                    <button className="hover:text-white transition-colors p-1" title="Edit">
                      <Edit2 size={18} />
                    </button>
                    <button className="hover:text-white transition-colors p-1" title="More">
                      <MoreVertical size={18} />
                    </button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

export default TicketTable;
