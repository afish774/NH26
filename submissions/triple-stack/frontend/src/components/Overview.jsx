import React from 'react';
import StatsCards from './StatsCards';
import TicketTable from './TicketTable';

export default function Overview() {
  return (
    <div className="animate-in fade-in duration-500">
      <StatsCards />
      <div className="mt-10">
        <h2 className="text-lg font-bold mb-6 text-gray-100">Recent Tickets</h2>
        <TicketTable />
      </div>
    </div>
  );
}
