import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ReferenceLine, ResponsiveContainer
} from 'recharts';
import './App.css';

const API_BASE_URL = 'http://127.0.0.1:8000/api';

function App() {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [totalSteps, setTotalSteps] = useState(0);
  const [telemetryData, setTelemetryData] = useState(null);
  const [formattedPlot, setFormattedPlot] = useState([]); // ADDED THIS STATE
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const intervalRef = useRef(null);
  const fileInputRef = useRef(null);

  // Robust fetch with retry logic
  const fetchTotalSteps = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/total-steps`);
      if (!response.ok) throw new Error("Backend not ready");
      const data = await response.json();
      setTotalSteps(data.total_steps);
    } catch (error) {
      console.warn("Backend not ready, retrying in 2 seconds...");
      setTimeout(fetchTotalSteps, 2000);
    }
  }, []);

  const fetchTelemetryData = useCallback(async (index) => {
    try {
      const response = await fetch(`${API_BASE_URL}/telemetry?index=${index}`);
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      const data = await response.json();
      // Ensure we create a brand new object to force Recharts to detect a change
      setTelemetryData({ ...data });
    } catch (error) {
      console.error("Critical Error fetching telemetry:", error);
    }
  }, []);

  // Initial setup
  useEffect(() => {
    fetchTotalSteps();
  }, [fetchTotalSteps]);

  // Telemetry fetcher
  useEffect(() => {
    let isMounted = true;
    if (totalSteps > 0) {
      console.log(`Fetching index ${currentIndex}`);
      fetch(`${API_BASE_URL}/telemetry?index=${currentIndex}&t=${Date.now()}`)
        .then(res => res.json())
        .then(data => {
          if (isMounted) {
            setTelemetryData({ ...data });
            const plotData = data.historical_plot.map(item => ({
              ...item,
              Time: new Date(item.Timestamp).toLocaleDateString([], { month: 'short', year: '2-digit' })
            }));
            setFormattedPlot(plotData);
          }
        })
        .catch(err => console.error(err));
    }
    return () => { isMounted = false; };
  }, [currentIndex, totalSteps]);

  // Playback logic
  useEffect(() => {
    if (isPlaying && totalSteps > 0) {
      if (intervalRef.current) clearInterval(intervalRef.current);
      intervalRef.current = setInterval(() => {
        setCurrentIndex((prev) => {
          const next = Math.min(prev + playbackSpeed, totalSteps - 1);
          if (next >= totalSteps - 1) { setIsPlaying(false); }
          return next;
        });
      }, 100);
    } else {
      if (intervalRef.current) clearInterval(intervalRef.current);
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [isPlaying, totalSteps, playbackSpeed]);

  const handleFileUpload = async (event) => {
    const file = event.target.files[0];
    if (!file) return;

    setIsUploading(true);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch(`${API_BASE_URL}/upload-data`, {
        method: 'POST',
        body: formData,
      });
      if (response.ok) {
        await fetchTotalSteps();
        setCurrentIndex(0);
        setIsPlaying(false);
        alert("Data uploaded and processed successfully!");
      }
    } catch (error) {
      alert("Upload failed.");
    } finally {
      setIsUploading(false);
    }
  };

  if (!telemetryData) return <div className="container">Initializing Digital Twin...</div>;

  const { metadata, telemetry, forecasting } = telemetryData;

  return (
    <div className="container">
      <header className="header">
        <h1>PHE Digital Twin Dashboard</h1>
        <div className="upload-section">
          <input 
            type="file" 
            ref={fileInputRef} 
            onChange={handleFileUpload} 
            style={{ display: 'none' }} 
            accept=".xlsx,.csv"
          />
          <button 
            className="upload-btn" 
            onClick={() => fileInputRef.current.click()}
            disabled={isUploading}
          >
            {isUploading ? 'Processing...' : 'Upload New Data (.xlsx)'}
          </button>
        </div>
      </header>

      <div className="controls-bar">
        <div className="playback-controls">
          <button className="play-btn" onClick={() => setIsPlaying(!isPlaying)}>
            {isPlaying ? 'Pause' : 'Play Simulation'}
          </button>
          <div className="speed-control">
            <span>Speed:</span>
            <select value={playbackSpeed} onChange={(e) => setPlaybackSpeed(Number(e.target.value))}>
              <option value={1}>1x</option>
              <option value={10}>10x</option>
              <option value={50}>50x</option>
            </select>
          </div>
        </div>
        <div className="scrubber-container">
          <input
            type="range"
            min="0"
            max={totalSteps - 1}
            value={currentIndex}
            onChange={(e) => { setCurrentIndex(Number(e.target.value)); setIsPlaying(false); }}
            className="timeline-slider"
          />
          <span className="timestamp-label">{metadata.timestamp}</span>
        </div>
      </div>

      <div className="main-grid">
        <div className="stats-panel">
          <div className="card-mini">
            <h3>Predicted Maintenance</h3>
            <div className="predictive-date">{forecasting.maintenance_date}</div>
          </div>
          <div className="card-mini">
            <h3>Current Fouling</h3>
            <div className={`fouling-value ${telemetry.fouling_factor > telemetry.fouling_limit ? 'alarm' : ''}`}>
              {telemetry.fouling_factor.toFixed(6)}
            </div>
          </div>
        </div>

        <div className="charts-grid">
          <div className="chart-card">
            <h3>Hot Side Parameters</h3>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={formattedPlot}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="Time" />
                <YAxis label={{ value: '°C / m³/h', angle: -90, position: 'insideLeft' }} />
                <Tooltip />
                <Legend verticalAlign="top" />
                <Line type="monotone" dataKey="T_hot_in" stroke="#ff4d4d" dot={false} name="Inlet Temp" strokeWidth={2} isAnimationActive={false} />
                <Line type="monotone" dataKey="T_hot_out" stroke="#ff9999" dot={false} name="Outlet Temp" strokeWidth={2} isAnimationActive={false} />
                <Line type="monotone" dataKey="Flow_hot_out" stroke="#ffcc00" dot={false} name="Flow Rate" isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="chart-card">
            <h3>Cold Side Parameters</h3>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={formattedPlot}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="Time" />
                <YAxis label={{ value: '°C / %', angle: -90, position: 'insideLeft' }} />
                <Tooltip />
                <Legend verticalAlign="top" />
                <Line type="monotone" dataKey="T_cold_in" stroke="#3399ff" dot={false} name="Inlet Temp" strokeWidth={2} isAnimationActive={false} />
                <Line type="monotone" dataKey="Valve_position" stroke="#003366" dot={false} name="Valve %" isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="chart-card wide">
            <h3>Fouling Factor Analysis (Rf)</h3>
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={formattedPlot}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="Time" />
                <YAxis domain={[0, telemetry.fouling_limit * 1.5]} />
                <Tooltip />
                <ReferenceLine y={telemetry.fouling_limit} stroke="red" strokeDasharray="5 5" label="Limit" />
                <Line type="monotone" dataKey="Fouling_Factor_Smooth" stroke="#8884d8" dot={false} strokeWidth={3} name="Rf (Fouling Factor)" isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;

