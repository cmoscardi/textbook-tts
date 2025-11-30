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
  const isMountedRef = useRef(true);

  // Update conversion when prop changes
  useEffect(() => {
    setConversion(existingConversion);
  }, [existingConversion]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      isMountedRef.current = false;
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
      }
    };
  }, []);

  // Start polling if there's an active conversion
  useEffect(() => {
    if (conversion && (conversion.status === 'pending' || conversion.status === 'running')) {
      startPolling(conversion.job_id);
    }
  }, [conversion]);

  const startPolling = (jobId) => {
    // Don't start if already polling
    if (pollingIntervalRef.current) {
      return;
    }

    pollingIntervalRef.current = setInterval(async () => {
      if (!isMountedRef.current) {
        clearInterval(pollingIntervalRef.current);
        return;
      }

      try {
        const { data, error } = await supabase
          .from('file_conversions')
          .select('*')
          .eq('job_id', jobId)
          .limit(1)
          .single();

        if (error) throw error;

        if (data) {
          setConversion(data);

          // Stop polling if completed or failed
          if (data.status === 'completed' || data.status === 'failed') {
            clearInterval(pollingIntervalRef.current);
            pollingIntervalRef.current = null;

            if (data.status === 'completed' && onConversionComplete) {
              onConversionComplete(data);
            }
          }
        }
      } catch (err) {
        console.error('Error polling conversion status:', err);
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
        setError('Failed to check conversion status');
      }
    }, 3000); // Poll every 3 seconds
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
