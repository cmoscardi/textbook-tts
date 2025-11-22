import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { supabase } from '../lib/supabase.js';
import { useSession } from '../lib/SessionContext.jsx';

// Map to track active polling jobs outside of React state
const activePollingJobs = new Map();

export default function Files() {
  const { session } = useSession();
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [conversions, setConversions] = useState({}); // file_id -> conversion data
  const [parsings, setParsings] = useState({}); // file_id -> parsing data
  const [pollingIntervals, setPollingIntervals] = useState({}); // file_id -> interval ID
  const [audioFiles, setAudioFiles] = useState({}); // file_id -> signed URL cache

  useEffect(() => {
    if (session?.user) {
      fetchFiles();
      fetchConversions();
      fetchParsings();
    }
  }, [session]);

  // Clean up polling intervals on unmount
  useEffect(() => {
    return () => {
      // Only run cleanup on actual unmount
      console.log('Component unmounting, cleaning up polling intervals');
      activePollingJobs.forEach((_, jobId) => {
        activePollingJobs.set(jobId, false);
      });
      Object.values(pollingIntervals).forEach(intervalId => {
        clearInterval(intervalId);
      });
    };
  }, []); // Empty dependency array - only run on mount/unmount

  const fetchFiles = async () => {
    try {
      setLoading(true);
      setError('');

      const { data, error: fetchError } = await supabase
        .from('files')
        .select('*')
        .eq('user_id', session.user.id)
        .order('uploaded_at', { ascending: false });

      if (fetchError) {
        throw fetchError;
      }

      setFiles(data || []);
    } catch (err) {
      console.error('Error fetching files:', err);
      setError('Failed to load files');
    } finally {
      setLoading(false);
    }
  };

  const fetchConversions = async () => {
    try {
      const { data, error: fetchError } = await supabase
        .from('file_conversions')
        .select(`
          conversion_id,
          file_id,
          file_path,
          job_id,
          job_completion,
          status,
          created_at,
          updated_at
        `)
        .order('created_at', { ascending: false });

      if (fetchError) {
        throw fetchError;
      }

      // Group conversions by file_id, keeping only the most recent
      const conversionMap = {};
      data?.forEach(conversion => {
        if (!conversionMap[conversion.file_id] ||
            new Date(conversion.created_at) > new Date(conversionMap[conversion.file_id].created_at)) {
          conversionMap[conversion.file_id] = conversion;
        }
      });

      setConversions(conversionMap);

      // Start polling for active conversions
      Object.values(conversionMap).forEach(conversion => {
        if (conversion.status === 'pending' || conversion.status === 'running') {
          startPolling(conversion.job_id, conversion.file_id);
        }
      });

    } catch (err) {
      console.error('Error fetching conversions:', err);
      // Don't set error state here as it's not critical for the main functionality
    }
  };

  const fetchParsings = async () => {
    try {
      const { data, error: fetchError } = await supabase
        .from('file_parsings')
        .select(`
          parsing_id,
          file_id,
          job_id,
          job_completion,
          status,
          error_message,
          created_at,
          updated_at
        `)
        .order('created_at', { ascending: false });

      if (fetchError) {
        throw fetchError;
      }

      // Group parsings by file_id, keeping only the most recent
      const parsingMap = {};
      data?.forEach(parsing => {
        if (!parsingMap[parsing.file_id] ||
            new Date(parsing.created_at) > new Date(parsingMap[parsing.file_id].created_at)) {
          parsingMap[parsing.file_id] = parsing;
        }
      });

      setParsings(parsingMap);

    } catch (err) {
      console.error('Error fetching parsings:', err);
      // Don't set error state here as it's not critical for the main functionality
    }
  };

  const startPolling = (jobId, fileId) => {
    // Don't start multiple intervals for the same job
    if (activePollingJobs.has(jobId)) {
      console.log('Polling already exists for job_id:', jobId);
      return;
    }
    
    console.log('Starting polling for job_id:', jobId, 'file_id:', fileId);
    console.log('Current active jobs:', Array.from(activePollingJobs.keys()));

    // Mark job as active
    activePollingJobs.set(jobId, true);
    console.log('Marked job as active:', jobId, 'Map size:', activePollingJobs.size);
    
    const intervalId = setInterval(async () => {
      const isActive = activePollingJobs.get(jobId);
      console.log('Polling execution check for job_id:', jobId, 'isActive:', isActive);
      if (!isActive) {
        console.log('Polling marked inactive for job_id:', jobId, 'stopping execution');
        clearInterval(intervalId);
        activePollingJobs.delete(jobId);
        return;
      }
      
      try {
        const { data, error } = await supabase
          .from('file_conversions')
          .select('*')
          .eq('job_id', jobId)
          .limit(1);

        if (error) throw error;

        if (data && data.length > 0) {
          const conversion = data[0];
          console.log('Polling update for job_id:', jobId, 'status:', conversion.status, 'progress:', conversion.job_completion);

          // Check if we need to stop polling before updating state
          const shouldStop = conversion.status === 'completed' || conversion.status === 'failed';
          
          setConversions(prev => {
            // For active conversions, update the file's conversion
            // For completed/failed, keep them in state for downloads
            const newState = { ...prev };
            newState[fileId] = conversion;
            return newState;
          });

          // Stop polling after state update if conversion is done
          if (shouldStop) {
            console.log('Conversion finished for job_id:', jobId, 'final status:', conversion.status);
            activePollingJobs.set(jobId, false); // Mark as inactive to stop future executions
            clearInterval(intervalId);
            setPollingIntervals(prev => {
              const newIntervals = { ...prev };
              delete newIntervals[jobId];
              return newIntervals;
            });
          }
        } else {
          console.log('No data found for job_id:', jobId);
        }
      } catch (err) {
        console.error('Error polling conversion status:', err);
        activePollingJobs.set(jobId, false);
        clearInterval(intervalId);
        setPollingIntervals(prev => {
          const newIntervals = { ...prev };
          delete newIntervals[jobId];
          return newIntervals;
        });
      }
    }, 3000); // Poll every 3 seconds

    setPollingIntervals(prev => {
      const newState = {
        ...prev,
        [jobId]: intervalId
      };
      console.log('Updated polling intervals state:', Object.keys(newState));
      return newState;
    });
  };

  const stopPolling = (jobId) => {
    console.log('Stopping polling for job_id:', jobId);
    activePollingJobs.set(jobId, false); // Mark as inactive first
    if (pollingIntervals[jobId]) {
      clearInterval(pollingIntervals[jobId]);
      setPollingIntervals(prev => {
        const newIntervals = { ...prev };
        delete newIntervals[jobId];
        return newIntervals;
      });
    } else {
      console.log('No polling interval found for job_id:', jobId);
    }
  };

  const handleDownload = async (file) => {
    try {
      const { data, error } = await supabase.storage
        .from('files')
        .download(file.file_path);

      if (error) {
        throw error;
      }

      // Create download link
      const url = URL.createObjectURL(data);
      const link = document.createElement('a');
      link.href = url;
      link.download = file.file_name;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Download error:', err);
      setError(`Failed to download ${file.file_name}`);
    }
  };

  const handleAudioDownload = async (file) => {
    try {
      const conversion = conversions[file.file_id];
      if (!conversion || conversion.status !== 'completed' || !conversion.file_path) {
        setError('Audio file not available for download');
        return;
      }

      console.log('Attempting to download audio file:');
      console.log('- File ID:', file.file_id);
      console.log('- File name:', file.file_name);
      console.log('- Conversion file path:', conversion.file_path);
      console.log('- Conversion status:', conversion.status);

      // First, check if the file exists in storage
      console.log('Checking if file exists in storage...');
      const { data: listData, error: listError } = await supabase.storage
        .from('files')
        .list(conversion.file_path.substring(0, conversion.file_path.lastIndexOf('/')), {
          limit: 1000,
          search: conversion.file_path.substring(conversion.file_path.lastIndexOf('/') + 1)
        });

      if (listError) {
        console.error('Error listing files:', listError);
      } else {
        console.log('Files found in directory:', listData);
        const fileExists = listData && listData.some(f => f.name === conversion.file_path.substring(conversion.file_path.lastIndexOf('/') + 1));
        console.log('File exists in storage:', fileExists);
      }

      // Try direct download first (like PDF downloads)
      console.log('Attempting direct download method...');
      const { data: downloadData, error: downloadError } = await supabase.storage
        .from('files')
        .download(conversion.file_path);

      if (downloadError) {
        console.error('Direct download failed, trying signed URL method...');
        console.error('Download error details:', downloadError);
        
        // Fallback to signed URL method
        const { data: urlData, error: urlError } = await supabase.storage
          .from('files')
          .createSignedUrl(conversion.file_path, 3600); // 1 hour expiry

        if (urlError) {
          console.error('Signed URL method also failed:', urlError);
          throw urlError;
        }

        if (!urlData?.signedUrl) {
          console.error('No signed URL returned from Supabase');
          throw new Error('Failed to generate download URL');
        }

        console.log('Successfully generated signed URL:', urlData.signedUrl);

        // Use signed URL for download
        const link = document.createElement('a');
        link.href = urlData.signedUrl;
        link.download = `${file.file_name.replace('.pdf', '.mp3')}`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      } else {
        // Direct download succeeded
        console.log('Direct download successful, creating blob URL...');
        
        // Create download link using blob data (same as PDF download)
        const url = URL.createObjectURL(downloadData);
        const link = document.createElement('a');
        link.href = url;
        link.download = `${file.file_name.replace('.pdf', '.mp3')}`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        
        console.log('Download completed successfully');
      }

    } catch (err) {
      console.error('Audio download error:', err);
      console.error('Error details:', {
        message: err.message,
        code: err.code,
        statusCode: err.statusCode,
        details: err.details
      });
      
      // Provide more specific error messages
      let errorMessage = 'Failed to download audio file';
      if (err.message?.includes('Object not found')) {
        errorMessage = `Audio file not found in storage. Path: ${conversions[file.file_id]?.file_path || 'unknown'}`;
      } else if (err.message?.includes('Permission denied')) {
        errorMessage = 'Permission denied - you may not have access to this audio file';
      } else if (err.message?.includes('Failed to generate download URL')) {
        errorMessage = 'Could not generate download link for audio file';
      } else {
        errorMessage = `Failed to download audio file: ${err.message}`;
      }
      
      setError(errorMessage);
    }
  };

  const handleConvert = async (file) => {
    try {
      setError('');

      // Check if there's already an active conversion for this file
      const existingConversion = conversions[file.file_id];
      if (existingConversion && 
          (existingConversion.status === 'pending' || existingConversion.status === 'running')) {
        setError('Conversion already in progress for this file');
        return;
      }

      // Call Supabase Edge Function for file conversion
      const { data, error } = await supabase.functions.invoke('convert-file', {
        body: {
          file_id: file.file_id,
          file_path: file.file_path
        }
      });

      if (error) {
        throw new Error(`Conversion service error: ${error.message}`);
      }

      if (!data?.id) {
        throw new Error('Invalid response from conversion service');
      }

      console.log('Conversion started:', data);
      console.log('Starting polling for job_id:', data.id, 'file_id:', file.file_id);

      // Create a pending conversion record locally for immediate UI feedback
      const pendingConversion = {
        conversion_id: `pending-${data.id}`,
        file_id: file.file_id,
        job_id: data.id,
        job_completion: 0,
        status: 'pending',
        file_path: '',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString()
      };

      // Update state - this will overwrite any completed conversion, which is fine for "Convert Again"
      setConversions(prev => ({
        ...prev,
        [file.file_id]: pendingConversion
      }));

      // Start polling for this conversion immediately
      console.log('About to start polling for job_id:', data.id);
      startPolling(data.id, file.file_id);

    } catch (err) {
      console.error('Convert error:', err);
      setError(`Failed to start conversion: ${err.message}`);
    }
  };

  const handleDelete = async (file) => {
    if (!confirm(`Are you sure you want to delete "${file.file_name}"?`)) {
      return;
    }

    try {
      // Delete from storage first
      const { error: storageError } = await supabase.storage
        .from('files')
        .remove([file.file_path]);

      if (storageError) {
        throw storageError;
      }

      // Delete from database
      const { error: dbError } = await supabase
        .from('files')
        .delete()
        .eq('file_id', file.file_id);

      if (dbError) {
        throw dbError;
      }

      // Update local state
      setFiles(files.filter(f => f.file_id !== file.file_id));
    } catch (err) {
      console.error('Delete error:', err);
      setError(`Failed to delete ${file.file_name}`);
    }
  };

  const formatFileSize = (bytes) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const renderConvertColumn = (file) => {
    const conversion = conversions[file.file_id];
    const parsing = parsings[file.file_id];

    // Check parsing status first
    if (!file.parsed_text) {
      // File hasn't been parsed yet
      if (parsing) {
        if (parsing.status === 'pending' || parsing.status === 'running') {
          // Parsing in progress
          return (
            <div className="flex flex-col gap-1">
              <div className="flex items-center gap-2">
                <div className="w-16 bg-gray-200 rounded-full h-2">
                  <div
                    className="bg-yellow-600 h-2 rounded-full transition-all duration-300"
                    style={{ width: `${parsing.job_completion}%` }}
                  ></div>
                </div>
                <span className="text-xs text-gray-600">{parsing.job_completion}%</span>
              </div>
              <span className="text-xs text-yellow-600">Parsing PDF...</span>
            </div>
          );
        } else if (parsing.status === 'failed') {
          // Parsing failed
          return (
            <div className="flex flex-col gap-1">
              <span className="text-xs text-red-600">Parse Failed</span>
              <span className="text-xs text-gray-500">Re-upload file</span>
            </div>
          );
        }
      }
      // No parsing record yet - file needs to be uploaded again with new system
      return (
        <div className="flex flex-col gap-1">
          <span className="text-xs text-gray-500">Not parsed</span>
          <span className="text-xs text-gray-400">Re-upload file</span>
        </div>
      );
    }

    // File is parsed, check conversion status
    if (!conversion) {
      // No conversion - show convert button
      return (
        <button
          onClick={() => handleConvert(file)}
          className="text-green-600 hover:text-green-900 flex items-center gap-1 px-3 py-1 border border-green-600 rounded hover:bg-green-50 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
          </svg>
          Convert
        </button>
      );
    }

    if (conversion.status === 'pending' || conversion.status === 'running') {
      // Active conversion - show progress
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

    if (conversion.status === 'completed') {
      // Completed - show download link
      return (
        <div className="flex flex-col gap-1">
          <button
            onClick={() => handleAudioDownload(file)}
            className="text-blue-600 hover:text-blue-900 flex items-center gap-1 px-2 py-1 text-sm"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Download MP3
          </button>
        </div>
      );
    }

    if (conversion.status === 'failed') {
      // Failed - show retry button
      return (
        <div className="flex flex-col gap-1">
          <span className="text-xs text-red-600">Failed</span>
          <button
            onClick={() => handleConvert(file)}
            className="text-orange-600 hover:text-orange-900 flex items-center gap-1 px-2 py-1 text-sm"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Retry
          </button>
        </div>
      );
    }

    return null;
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-gray-600">Loading files...</div>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
      <div className="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 mb-6">
        <h1 className="text-2xl font-bold text-gray-800">My Files</h1>
        <button
          onClick={() => {
            fetchFiles();
            fetchConversions();
          }}
          className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors w-full sm:w-auto"
        >
          Refresh
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-100 border border-red-400 text-red-700 rounded">
          {error}
        </div>
      )}

      {files.length === 0 ? (
        <div className="text-center py-12">
          <svg className="mx-auto h-12 w-12 text-gray-400 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          <h3 className="text-lg font-medium text-gray-900 mb-2">No files uploaded yet</h3>
          <p className="text-gray-500">Get started by uploading your first file.</p>
        </div>
      ) : (
        <>
          {/* Mobile Card View */}
          <div className="block lg:hidden space-y-4">
            {files.map((file) => (
              <div key={file.file_id} className="bg-white shadow rounded-lg p-4">
                {/* File name with icon */}
                <div className="flex items-start mb-3">
                  <svg className="h-5 w-5 text-gray-400 mr-2 mt-1 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  <div className="flex-1 min-w-0">
                    <h3 className="text-sm font-medium text-gray-900 break-words">{file.file_name}</h3>
                  </div>
                </div>

                {/* File metadata */}
                <div className="grid grid-cols-2 gap-2 mb-3 text-xs text-gray-600">
                  <div>
                    <span className="font-medium">Size:</span> {formatFileSize(file.file_size)}
                  </div>
                  <div>
                    <span className="font-medium">Type:</span> {file.mime_type || 'Unknown'}
                  </div>
                  <div className="col-span-2">
                    <span className="font-medium">Uploaded:</span> {formatDate(file.uploaded_at)}
                  </div>
                </div>

                {/* Convert status */}
                <div className="mb-3 pb-3 border-b border-gray-200">
                  <div className="text-xs font-medium text-gray-500 mb-1">Conversion Status</div>
                  {renderConvertColumn(file)}
                </div>

                {/* Actions */}
                <div className="flex flex-wrap gap-2">
                  {file.parsed_text && (
                    <Link
                      to={`/app/view/${file.file_id}`}
                      className="flex-1 min-w-[100px] text-center px-3 py-2 text-sm text-purple-600 bg-purple-50 hover:bg-purple-100 rounded flex items-center justify-center gap-1 transition-colors"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                      </svg>
                      View
                    </Link>
                  )}
                  <button
                    onClick={() => handleDownload(file)}
                    className="flex-1 min-w-[100px] px-3 py-2 text-sm text-blue-600 bg-blue-50 hover:bg-blue-100 rounded flex items-center justify-center gap-1 transition-colors"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    Download
                  </button>
                  <button
                    onClick={() => handleDelete(file)}
                    className="flex-1 min-w-[100px] px-3 py-2 text-sm text-red-600 bg-red-50 hover:bg-red-100 rounded flex items-center justify-center gap-1 transition-colors"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* Desktop Table View */}
          <div className="hidden lg:block bg-white shadow rounded-lg overflow-hidden">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Name
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Size
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Type
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Uploaded
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Convert
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {files.map((file) => (
                    <tr key={file.file_id} className="hover:bg-gray-50">
                      <td className="px-6 py-4 max-w-xs">
                        <div className="flex items-center">
                          <svg className="h-5 w-5 text-gray-400 mr-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                          </svg>
                          <div className="min-w-0">
                            <div className="text-sm font-medium text-gray-900 break-words">
                              {file.file_name}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {formatFileSize(file.file_size)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {file.mime_type || 'Unknown'}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {formatDate(file.uploaded_at)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                        {renderConvertColumn(file)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                        <div className="flex space-x-2">
                          {file.parsed_text && (
                            <Link
                              to={`/app/view/${file.file_id}`}
                              className="text-purple-600 hover:text-purple-900 flex items-center gap-1"
                            >
                              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                              </svg>
                              View
                            </Link>
                          )}
                          <button
                            onClick={() => handleDownload(file)}
                            className="text-blue-600 hover:text-blue-900 flex items-center gap-1"
                          >
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                            </svg>
                            Download
                          </button>
                          <button
                            onClick={() => handleDelete(file)}
                            className="text-red-600 hover:text-red-900 flex items-center gap-1"
                          >
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                            </svg>
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
