/**
 * Trip Tracking Controls & Live Voyage Manager Component.
 */

import React, { useState } from 'react';
import {
  Anchor,
  CheckCircle2,
  Clock,
  History,
  Navigation,
  Pause,
  Play,
  RotateCcw,
  Send,
  Square,
  TrendingUp,
} from 'lucide-react';
import { Coordinate, TripResponse, TripSummary } from '../types';

interface TripControlsProps {
  activeTrip: TripResponse | null;
  startPosition: Coordinate | null;
  destinationPosition: Coordinate | null;
  isStartingTrip: boolean;
  isUpdatingTrip: boolean;
  isStoppingTrip: boolean;
  isSimulating: boolean;
  tripSummaryData: TripSummary | null;
  onStartTrip: () => void;
  onUpdateGps: () => void;
  onToggleSimulation: () => void;
  onStopTrip: () => void;
  onFetchTripSummary: () => void;
  onOpenHistory: () => void;
}

export const TripControls: React.FC<TripControlsProps> = ({
  activeTrip,
  startPosition,
  destinationPosition,
  isStartingTrip,
  isUpdatingTrip,
  isStoppingTrip,
  isSimulating,
  tripSummaryData,
  onStartTrip,
  onUpdateGps,
  onToggleSimulation,
  onStopTrip,
  onFetchTripSummary,
  onOpenHistory,
}) => {
  return (
    <div className="trip-controls-card">
      <div className="card-header">
        <div className="header-title">
          <Anchor size={18} className="text-emerald" />
          <span>Trip Tracking</span>
        </div>
        <button className="btn-icon" onClick={onOpenHistory} title="View Saved Trip History">
          <History size={16} />
        </button>
      </div>

      <div className="card-body">
        {!activeTrip || activeTrip.status === 'completed' ? (
          <div className="trip-inactive-state">
            <p className="state-hint">
              {activeTrip?.status === 'completed'
                ? 'Voyage is completed. Start a new trip or review trip summary.'
                : 'Initialize an active voyage to record GPS coordinates and track points.'}
            </p>

            <div className="button-group-vertical">
              <button
                className="btn btn-success btn-block"
                onClick={onStartTrip}
                disabled={!startPosition || !destinationPosition || isStartingTrip}
              >
                <Play size={16} />
                <span>{isStartingTrip ? 'Starting Voyage...' : 'Start New Trip'}</span>
              </button>

              <button className="btn btn-secondary btn-block" onClick={onOpenHistory}>
                <History size={16} />
                <span>View Trip History</span>
              </button>
            </div>
          </div>
        ) : (
          <div className="trip-active-state">
            {/* Active Voyage Metadata */}
            <div className="active-trip-header">
              <div className="trip-meta">
                <span className="trip-badge">LIVE TRIP</span>
                <span className="trip-id" title={activeTrip.trip_id}>
                  {activeTrip.trip_id.length > 22
                    ? `${activeTrip.trip_id.slice(0, 18)}...`
                    : activeTrip.trip_id}
                </span>
              </div>
              <span className="badge-active">ACTIVE</span>
            </div>

            {/* Trip Kinematic Metrics */}
            <div className="trip-metrics-grid">
              <div className="trip-metric-card">
                <span className="metric-title">Distance Travelled</span>
                <span className="metric-primary text-emerald">
                  {activeTrip.distance_travelled_nm.toFixed(2)} NM
                </span>
                <span className="metric-secondary">
                  {activeTrip.distance_travelled_km.toFixed(2)} km
                </span>
              </div>

              <div className="trip-metric-card">
                <span className="metric-title">Elapsed Time</span>
                <span className="metric-primary text-cyan">
                  {Math.floor(activeTrip.elapsed_time_minutes / 60)}h{' '}
                  {Math.round(activeTrip.elapsed_time_minutes % 60)}m
                </span>
                <span className="metric-secondary">{activeTrip.elapsed_time_minutes.toFixed(1)} min</span>
              </div>

              <div className="trip-metric-card">
                <span className="metric-title">Track Points</span>
                <span className="metric-primary">{activeTrip.track_points_count}</span>
                <span className="metric-secondary">GPS Fixes</span>
              </div>
            </div>

            {/* Live Trip Action Buttons */}
            <div className="trip-actions-grid">
              <button
                className="btn btn-primary btn-sm"
                onClick={onUpdateGps}
                disabled={isUpdatingTrip}
                title="Send single GPS fix to backend"
              >
                <Send size={14} />
                <span>{isUpdatingTrip ? 'Sending...' : 'Send GPS Fix'}</span>
              </button>

              <button
                className={`btn ${isSimulating ? 'btn-warning' : 'btn-secondary'} btn-sm`}
                onClick={onToggleSimulation}
                title="Simulate continuous vessel movement along route"
              >
                {isSimulating ? <Pause size={14} /> : <Play size={14} />}
                <span>{isSimulating ? 'Pause Auto-Sim' : 'Auto-Simulate'}</span>
              </button>
            </div>

            <div className="trip-secondary-actions">
              <button className="btn btn-outline-secondary btn-sm" onClick={onFetchTripSummary}>
                <TrendingUp size={14} />
                <span>Summary</span>
              </button>

              <button
                className="btn btn-danger btn-sm"
                onClick={onStopTrip}
                disabled={isStoppingTrip}
              >
                <Square size={14} />
                <span>{isStoppingTrip ? 'Stopping...' : 'Stop & Finalize'}</span>
              </button>
            </div>
          </div>
        )}

        {/* Modal-like Summary Card Inline if Requested */}
        {tripSummaryData && (
          <div className="summary-inline-card">
            <div className="summary-inline-header">
              <span>Trip Summary</span>
            </div>
            <div className="summary-inline-body">
              <div>Total Distance: <strong>{tripSummaryData.distance_travelled_nm.toFixed(2)} NM</strong> ({tripSummaryData.distance_travelled_km.toFixed(2)} km)</div>
              <div>Duration: <strong>{tripSummaryData.elapsed_time_minutes} minutes</strong></div>
              <div>Status: <strong>{tripSummaryData.status.toUpperCase()}</strong></div>
              <div>Total Points: <strong>{tripSummaryData.track_points_count}</strong></div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
