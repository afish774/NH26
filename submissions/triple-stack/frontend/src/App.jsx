import React, { useState } from 'react';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import Overview from './components/Overview';
import Connect from './components/Connect';
import Analysis from './components/Analysis';
import About from './components/About';

function App() {
  const [currentTab, setCurrentTab] = useState('Overview');

  const renderContent = () => {
    switch (currentTab) {
      case 'Overview': return <Overview />;
      case 'Connect': return <Connect />;
      case 'Analysis': return <Analysis />;
      case 'About': return <About />;
      default: return <Overview />;
    }
  };

  return (
    <div className="flex h-screen w-full bg-black text-white overflow-hidden font-sans">
      <Sidebar currentTab={currentTab} setCurrentTab={setCurrentTab} />
      <div className="flex-1 flex flex-col h-full overflow-hidden border-l border-borderColor relative">
        {currentTab === 'Overview' && <Header />}
        <main className={`flex-1 overflow-y-auto w-full max-w-[1400px] xl:max-w-none 2xl:max-w-[1600px] mx-auto ${currentTab !== 'Connect' ? 'p-8 lg:p-10 hide-scrollbar' : 'flex flex-col'}`}>
          {renderContent()}
        </main>
      </div>
    </div>
  );
}

export default App;
