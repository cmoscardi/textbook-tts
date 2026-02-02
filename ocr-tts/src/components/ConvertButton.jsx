import { useState, useEffect, useRef } from 'react';
import { supabase } from '../lib/supabase.js';

export default function ConvertButton({
  fileId,
  filePath,
  existingConversion = null,
  onConversionComplete,
  compact = false
}) {
  const [conversion, setConversion] = useState(existingConversion);
  const [error, setError] = useState('');
  const [isStarting, setIsStarting] = useState(false);
  const pollingIntervalRef = useRef(null);
  const currentJobIdRef = useRef(null);
  const isMountedRef = useRef(true);

  // Update conversion when prop changes
  useEffect(() => {
    setConversion(existingConversion);
  }, [existingConversion]);

  // Set mounted state and cleanup polling on unmount
  useEffect(() => {
    isMountedRef.current = true;
    console.log('[Mount] ConvertButton mounted');

    return () => {
      console.log('[Mount] ConvertButton unmounting');
      isMountedRef.current = false;
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
        currentJobIdRef.current = null;
      }
    };
  }, []);

  // Start polling if there's an active conversion
  useEffect(() => {
    if (conversion && (conversion.status === 'pending' || conversion.status === 'running')) {
      startPolling(conversion.job_id);
    }
  }, [conversion]);

  // Page Visibility API listener - force check when page becomes visible
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        // Page became visible - force a status check
        if (conversion && conversion.job_id &&
            (conversion.status === 'pending' || conversion.status === 'running')) {
          console.log('Page visible - forcing conversion status check');
          checkConversionStatus(conversion.job_id);
        }
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [conversion]);

  const checkConversionStatus = async (jobId) => {
    console.log('[Poll] Checking status for job:', jobId);

    if (!isMountedRef.current) {
      console.log('[Poll] Component unmounted, skipping');
      return;
    }

    try {
      const { data, error } = await supabase
        .from('file_conversions')
        .select('*')
        .eq('job_id', jobId)
        .limit(1)
        .maybeSingle();

      if (error) {
        console.error('[Poll] Error checking conversion status:', error);
        // Don't clear interval on error - keep trying
        return;
      }

      if (data) {
        console.log('[Poll] Conversion status update:', data.status, data.job_completion + '%');
        setConversion(data);

        // Stop polling if completed or failed
        if (data.status === 'completed' || data.status === 'failed') {
          console.log('[Poll] Conversion finished, stopping polling');
          if (pollingIntervalRef.current) {
            clearInterval(pollingIntervalRef.current);
            pollingIntervalRef.current = null;
            currentJobIdRef.current = null;
          }

          if (data.status === 'completed' && onConversionComplete) {
            onConversionComplete(data);
          }
        }
      } else {
        console.log('[Poll] No conversion record found yet for job:', jobId);
        // Don't clear interval - record might not be created yet
      }
    } catch (err) {
      console.error('[Poll] Exception polling conversion status:', err);
      // Don't clear interval - keep trying
    }
  };

  const startPolling = (jobId) => {
    // Defensive check: don't poll with invalid job IDs
    if (!jobId || jobId === 'pending') {
      console.warn('Invalid job_id for polling:', jobId);
      return;
    }

    // If already set up for this exact job, don't restart
    if (currentJobIdRef.current === jobId) {
      console.log('Already polling for job:', jobId);
      return;
    }

    // Clear any existing interval for a different job
    if (pollingIntervalRef.current) {
      console.log('Clearing existing polling interval for different job');
      clearInterval(pollingIntervalRef.current);
      pollingIntervalRef.current = null;
    }

    console.log('Starting polling for job:', jobId);
    currentJobIdRef.current = jobId;

    // Check immediately first
    checkConversionStatus(jobId);

    // Then poll every 3 seconds
    const intervalId = setInterval(() => {
      console.log('[Interval] Firing for job:', jobId);
      checkConversionStatus(jobId);
    }, 3000);
    pollingIntervalRef.current = intervalId;
    console.log('Polling interval created:', intervalId);
  };

  const handleConvert = async () => {
    try {
      setError('');
      setIsStarting(true);

      // Check for existing active conversion
      if (conversion && (conversion.status === 'pending' || conversion.status === 'running')) {
        setError('Conversion already in progress');
        setIsStarting(false);
        return;
      }

      // Call the convert-file Edge Function
      const { data, error } = await supabase.functions.invoke('convert-file', {
        body: {
          file_id: fileId,
          ...(filePath && { file_path: filePath })
        }
      });

      if (error) {
        throw new Error(`Conversion service error: ${error.message}`);
      }

      if (!data?.id) {
        throw new Error('Invalid response from conversion service');
      }

      // Create pending conversion record for immediate UI feedback
      const pendingConversion = {
        conversion_id: `pending-${data.id}`,
        file_id: fileId,
        job_id: data.id,
        job_completion: 0,
        status: 'pending',
        file_path: '',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString()
      };

      setConversion(pendingConversion);
      setIsStarting(false);

      // Start polling for updates
      startPolling(data.id);

    } catch (err) {
      console.error('Convert error:', err);
      setError(`Failed to start conversion: ${err.message}`);
      setIsStarting(false);
    }
  };

  // Render different states
  if (!conversion) {
    // Not converted - show convert button
    return (
      <div className="flex flex-col gap-1">
        <button
          onClick={handleConvert}
          disabled={isStarting}
          className="text-green-600 hover:text-green-900 flex items-center gap-1 px-3 py-1 border border-green-600 rounded hover:bg-green-50 disabled:bg-gray-100 disabled:text-gray-400 disabled:border-gray-300 transition-colors"
          title="Convert to audio"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
          </svg>
          {isStarting ? 'Starting...' : 'Convert'}
        </button>
        {error && <span className="text-xs text-red-600">{error}</span>}
      </div>
    );
  }

  if (conversion.status === 'pending' || conversion.status === 'running') {
    // Converting - show progress
    return (
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <div className="w-16 bg-gray-200 rounded-full h-2">
            <div
              className="bg-blue-600 h-2 rounded-full transition-all duration-300"
              style={{ width: `${conversion.job_completion}%` }}
            ></div>
          </div>
          <span className="text-xs text-gray-600">{conversion.job_completion}%</span>
        </div>
        <span className="text-xs text-blue-600">
          {conversion.status === 'pending' ? 'Starting...' : 'Converting...'}
        </span>
      </div>
    );
  }

  if (conversion.status === 'failed') {
    // Failed - show retry button
    return (
      <div className="flex flex-col gap-1">
        <button
          onClick={handleConvert}
          disabled={isStarting}
          className="text-red-600 hover:text-red-900 flex items-center gap-1 px-3 py-1 border border-red-600 rounded hover:bg-red-50 disabled:bg-gray-100 transition-colors text-sm"
          title="Retry conversion"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          {isStarting ? 'Retrying...' : 'Retry'}
        </button>
        <span className="text-xs text-red-600">Conversion failed</span>
      </div>
    );
  }

  if (conversion.status === 'completed') {
    // Completed - show success state
    return (
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-1 text-green-600 text-sm">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span className="text-xs">Converted</span>
        </div>
      </div>
    );
  }

  return null;
}
