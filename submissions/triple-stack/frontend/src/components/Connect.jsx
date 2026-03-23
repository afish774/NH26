import React, { useState, useRef, useEffect } from 'react';
import { Sparkles, Paperclip, Mic, ArrowUp, X, ThumbsUp, ThumbsDown, MicOff } from 'lucide-react';

export default function Connect() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = (overrideText) => {
    const userMsg = (overrideText || input).trim();
    if (!userMsg || loading) return;
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
    setLoading(true);

    import('../lib/api').then(({ sendChat }) => {
      const history = messages.map(m => ({ role: m.role, content: m.content }));
      sendChat(userMsg, history, null).then(res => {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: res.reply,
          confidence: res.confidence
        }]);
        if (res.create_ticket) {
          setTimeout(() => {
            setMessages(prev => [...prev, {
              role: 'assistant',
              content: `Would you like to raise a support ticket for this?`,
              showTicketPrompt: true,
              userMsgBackup: userMsg
            }]);
            setLoading(false);
          }, 700);
        } else {
          setLoading(false);
        }
      }).catch(e => {
        console.error(e);
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: 'Sorry, I am facing a connection issue. Please try again.',
          confidence: 0
        }]);
        setLoading(false);
      });
    });
  };

  const handleCreateTicket = (userMsg) => {
    if (!userMsg) return;
    import('../lib/api').then(({ createTicket }) => {
      setMessages(prev => prev.map(m =>
        m.showTicketPrompt ? { ...m, showTicketPrompt: false, content: 'Creating your ticket...' } : m
      ));
      createTicket(userMsg.slice(0, 80), userMsg).then(() => {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: '✅ Support ticket created successfully. Our team will respond shortly.',
          confidence: 1
        }]);
      }).catch(() => {
        setMessages(prev => [...prev, { role: 'assistant', content: '❌ Failed to create ticket. Please try again.' }]);
      });
    });
  };

  // ── ATTACH: open file picker, send image to screenshot API ──
  const handleAttach = () => fileInputRef.current?.click();

  const handleFileChange = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const base64 = reader.result.split(',')[1];
      setMessages(prev => [...prev, { role: 'user', content: `📎 Attached: ${file.name}` }]);
      setLoading(true);
      import('../lib/api').then(({ analyzeScreenshot }) => {
        analyzeScreenshot(base64, file.type).then(res => {
          setMessages(prev => [...prev, {
            role: 'assistant',
            content: res.analysis || res.message || 'Screenshot analyzed. What would you like to do?',
            confidence: res.confidence
          }]);
          setLoading(false);
        }).catch(() => {
          setMessages(prev => [...prev, { role: 'assistant', content: 'Could not analyze the attachment. Please describe the issue instead.' }]);
          setLoading(false);
        });
      });
    };
    reader.readAsDataURL(file);
    e.target.value = '';
  };

  // ── RECORD: MediaRecorder API ──
  const handleRecord = async () => {
    if (isRecording) {
      mediaRecorderRef.current?.stop();
      setIsRecording(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      audioChunksRef.current = [];
      recorder.ondataavailable = e => audioChunksRef.current.push(e.data);
      recorder.onstop = () => {
        stream.getTracks().forEach(t => t.stop());
        setMessages(prev => [...prev, { role: 'user', content: '🎤 Voice message recorded' }]);
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: 'Voice received. Transcription is not yet available — please type your question below and I will assist you.'
        }]);
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setIsRecording(true);
    } catch {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '🎤 Microphone access denied. Please allow microphone permission in your browser settings.'
      }]);
    }
  };

  const hasStarted = messages.length > 0;

  return (
    <div className="relative w-full h-full bg-black flex flex-col items-center overflow-hidden font-sans">

      {/* Hidden file input */}
      <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleFileChange} />
      
      {/* INITIAL CENTRIC PROMPT STATE */}
      <div className={`transition-all duration-[800ms] ease-[cubic-bezier(0.16,1,0.3,1)] absolute inset-0 flex flex-col items-center justify-center w-full px-6 pb-12 mt-[30px] z-10 ${
        hasStarted ? 'opacity-0 -translate-y-[15%] scale-[0.97] pointer-events-none' : 'opacity-100 translate-y-0 scale-100'
      }`}>
        <h1 className="text-4xl md:text-5xl font-bold text-white mb-4 tracking-tight">
          IT Support, <span className="text-[#f59e0b] italic font-serif">Simplified</span>
        </h1>
        <p className="text-gray-400 text-[15px] mb-8">
          Ask your question, report an issue, or request help, we're here for you.
        </p>

        <div className="w-full max-w-3xl bg-white rounded-[24px] p-5 flex flex-col relative min-h-[160px] shadow-lg focus-within:ring-2 focus-within:ring-brand transition-all duration-300">
          <div className="flex items-start gap-2 mb-2">
            <Sparkles size={20} className="text-black shrink-0 mt-0.5" />
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
              placeholder="Ask AI a question or make a request"
              className="w-full bg-transparent text-black text-[15px] resize-none outline-none leading-relaxed placeholder:text-gray-500 min-h-[60px]"
            />
          </div>
          <div className="mt-auto flex items-center justify-between pt-2">
            <div className="flex items-center gap-2">
              <button onClick={handleAttach} className="bg-black hover:bg-gray-800 text-white rounded-full px-4 py-2 flex items-center gap-2 text-xs font-medium transition-colors">
                <Paperclip size={14} /> Attach
              </button>
              <button onClick={handleRecord} className={`${isRecording ? 'bg-red-600 hover:bg-red-700 animate-pulse' : 'bg-black hover:bg-gray-800'} text-white rounded-full px-4 py-2 flex items-center gap-2 text-xs font-medium transition-colors`}>
                {isRecording ? <><MicOff size={14} /> Stop</> : <><Mic size={14} /> Record</>}
              </button>
            </div>
            <button onClick={() => handleSend()} disabled={!input.trim()} className="bg-black hover:bg-gray-800 text-white rounded-full p-2.5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
              <ArrowUp size={18} />
            </button>
          </div>
        </div>

        <p className="text-[10px] text-gray-500 mt-6 tracking-wide text-center">
          AI Confidence Level: Determined per response
        </p>
      </div>

      {/* CHAT SESSION STATE */}
      <div className={`w-full flex-1 overflow-y-auto px-6 pb-40 pt-10 transition-all duration-[1000ms] ease-[cubic-bezier(0.16,1,0.3,1)] absolute inset-0 max-w-5xl mx-auto hide-scrollbar z-0 ${
        hasStarted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-[10%] pointer-events-none'
      }`}>
        <div className="flex flex-col items-center space-y-6 w-full">
          
          <div onClick={() => setMessages([])} className="w-[38px] h-[38px] bg-[#1a1a1a] rounded-full flex items-center justify-center cursor-pointer border border-[#333] hover:bg-[#252525] transition-colors mb-2">
            <X size={18} className="text-gray-400" />
          </div>
          <span className="bg-white text-black text-[11px] font-bold px-4 py-1.5 rounded-full mb-8">Today</span>

          {messages.map((msg, i) => (
            <div key={i} className={`w-full flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'} gap-3 mb-6`}>
              {msg.role === 'assistant' && (
                <>
                  <div className="w-8 h-8 rounded-full bg-[#0055ff] flex items-center justify-center text-white shrink-0 shadow-lg">
                    <Sparkles size={14} fill="currentColor" />
                  </div>
                  <div className="flex flex-col max-w-[70%]">
                    <div className="bg-brand text-black px-5 py-3.5 rounded-2xl rounded-tl-sm text-[14px] font-medium shadow-sm leading-relaxed">
                      {msg.content}
                    </div>
                    {msg.confidence !== undefined && (
                      <span className="text-[10px] text-gray-500 mt-1.5 px-1 font-medium">
                        AI Confidence Level : {Math.round(msg.confidence * 100)}%
                      </span>
                    )}
                    {msg.showTicketPrompt && (
                      <div className="flex gap-2 ml-1 mt-3">
                        <button onClick={() => handleCreateTicket(msg.userMsgBackup)} className="bg-white hover:bg-gray-100 text-black text-xs font-bold px-3.5 py-1.5 rounded shadow-sm flex items-center gap-1.5 transition-colors">
                          Yes <ThumbsUp size={12} className="text-green-500" />
                        </button>
                        <button onClick={() => setMessages(prev => prev.map(m => m === msg ? { ...m, showTicketPrompt: false, content: 'Okay, let me know if you need anything else.' } : m))} className="bg-white hover:bg-gray-100 text-black text-xs font-bold px-3.5 py-1.5 rounded shadow-sm flex items-center gap-1.5 transition-colors">
                          No <ThumbsDown size={12} className="text-red-500" />
                        </button>
                      </div>
                    )}
                  </div>
                </>
              )}
              {msg.role === 'user' && (
                <>
                  <div className="bg-white text-black px-5 py-3.5 rounded-2xl rounded-tr-sm text-[14px] font-medium shadow-sm max-w-[70%] leading-relaxed">
                    {msg.content}
                  </div>
                  <div className="w-8 h-8 rounded-full bg-[#c98e77] flex items-center justify-center text-white text-sm font-bold shrink-0 shadow-lg">S</div>
                </>
              )}
            </div>
          ))}
          
          {loading && (
            <div className="w-full flex justify-start gap-3">
              <div className="w-8 h-8 rounded-full bg-[#0055ff] flex items-center justify-center text-white shrink-0">
                <Sparkles size={14} fill="currentColor" />
              </div>
              <div className="bg-[#111] px-5 py-4 rounded-2xl rounded-tl-sm border border-[#222]">
                <div className="flex gap-1.5 items-center">
                  <span className="w-1.5 h-1.5 bg-gray-500 rounded-full animate-bounce" style={{animationDelay:'0ms'}} />
                  <span className="w-1.5 h-1.5 bg-gray-500 rounded-full animate-bounce" style={{animationDelay:'150ms'}} />
                  <span className="w-1.5 h-1.5 bg-gray-500 rounded-full animate-bounce" style={{animationDelay:'300ms'}} />
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* FIXED PILL INPUT BAR */}
      <div className={`absolute transition-all duration-[800ms] ease-[cubic-bezier(0.16,1,0.3,1)] w-full max-w-3xl px-4 z-20 ${
        hasStarted ? 'bottom-8 opacity-100 translate-y-0 scale-100' : '-bottom-32 opacity-0 translate-y-12 scale-95 pointer-events-none'
      }`}>
        <div className="w-full bg-white rounded-full p-2.5 flex items-center justify-between shadow-2xl focus-within:ring-2 focus-within:ring-brand/50 transition-shadow">
          <div className="flex items-center gap-2">
            <button onClick={handleAttach} title="Attach screenshot" className="bg-black hover:bg-gray-800 text-white rounded-full w-[38px] h-[38px] flex items-center justify-center transition-colors shadow-sm">
              <Paperclip size={16} />
            </button>
            <button onClick={handleRecord} title={isRecording ? 'Stop recording' : 'Record voice'} className={`${isRecording ? 'bg-red-600 hover:bg-red-700 animate-pulse' : 'bg-black hover:bg-gray-800'} text-white rounded-full w-[38px] h-[38px] flex items-center justify-center transition-colors shadow-sm`}>
              {isRecording ? <MicOff size={16} /> : <Mic size={16} />}
            </button>
          </div>
          <div className="flex items-center flex-1 mx-4 gap-2">
            <Sparkles size={18} className="text-gray-400 shrink-0" />
            <input
              type="text"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleSend(); } }}
              placeholder="Ask AI a question or make a request"
              className="w-full bg-transparent text-black text-[15px] font-medium outline-none placeholder:text-gray-400 placeholder:font-normal"
            />
          </div>
          <button onClick={() => handleSend()} disabled={!input.trim()} className="bg-black hover:bg-gray-800 text-white rounded-full w-[38px] h-[38px] flex items-center justify-center transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-sm shrink-0">
            <ArrowUp size={18} strokeWidth={2.5}/>
          </button>
        </div>
      </div>

    </div>
  );
}
