import { useState, useEffect } from 'react';
import { supabase } from '../lib/supabase.js';
import { useSession } from '../lib/SessionContext.jsx';

export default function Files() {
  const { session } = useSession();
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [conversions, setConversions] = useState({}); // file_id -> conversion data
  const [pollingIntervals, setPollingIntervals] = useState({}); // file_id -> interval ID
  const [audioFiles, setAudioFiles] = useState({}); // file_id -> signed URL cache

  useEffect(() => {
    if (session?.user) {
      fetchFiles();
      fetchConversions();
    }
  }, [session]);

  // Clean up polling intervals on unmount
  useEffect(() => {
    return () => {
      Object.values(pollingIntervals).forEach(clearInterval);
    };
  }, [pollingIntervals]);

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
          startPolling(conversion.file_id);
        }
      });

    } catch (err) {
      console.error('Error fetching conversions:', err);
      // Don't set error state here as it's not critical for the main functionality
    }
  };

  const startPolling = (fileId) => {
    // Don't start multiple intervals for the same file
    if (pollingIntervals[fileId]) {
      return;
    }

    const intervalId = setInterval(async () => {
      try {
        const { data, error } = await supabase
          .from('file_conversions')
          .select('*')
          .eq('file_id', fileId)
          .order('created_at', { ascending: false })
          .limit(1);

        if (error) throw error;

        if (data && data.length > 0) {
          const conversion = data[0];

          setConversions(prev => ({
            ...prev,
            [fileId]: conversion
          }));

          // Stop polling if conversion is complete or failed
          if (conversion.status === 'completed' || conversion.status === 'failed') {
            stopPolling(fileId);
          }
        }
      } catch (err) {
        console.error('Error polling conversion status:', err);
        stopPolling(fileId);
      }
    }, 3000); // Poll every 3 seconds

    setPollingIntervals(prev => ({
      ...prev,
      [fileId]: intervalId
    }));
  };

  const stopPolling = (fileId) => {
    if (pollingIntervals[fileId]) {
      clearInterval(pollingIntervals[fileId]);
      setPollingIntervals(prev => {
        const newIntervals = { ...prev };
        delete newIntervals[fileId];
        return newIntervals;
      });
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

      // Check if we have a cached URL
      if (audioFiles[file.file_id]) {
        const link = document.createElement('a');
        link.href = audioFiles[file.file_id];
        link.download = `${file.file_name.replace('.pdf', '.mp3')}`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        return;
      }

      // Generate signed URL for audio file
      const { data: urlData, error } = await supabase.storage
        .from('files')
        .createSignedUrl(conversion.file_path, 3600); // 1 hour expiry

      if (error) throw error;

      if (!urlData?.signedUrl) {
        throw new Error('Failed to generate download URL');
      }

      // Cache the URL
      setAudioFiles(prev => ({
        ...prev,
        [file.file_id]: urlData.signedUrl
      }));

      // Trigger download
      const link = document.createElement('a');
      link.href = urlData.signedUrl;
      link.download = `${file.file_name.replace('.pdf', '.mp3')}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);

    } catch (err) {
      console.error('Audio download error:', err);
      setError(`Failed to download audio file: ${err.message}`);
    }
  };

  const handleConvert = async (file) => {
    try {
      setError('');

      // Get the public URL for the file
      const { data: urlData } = await supabase.storage
        .from('files')
        .createSignedUrl(file.file_path, 3600); // 1 hour expiry

      if (!urlData?.signedUrl) {
        throw new Error('Failed to generate file URL');
      }

      // Get ML service URL from environment
      const mlServiceHost = import.meta.env.VITE_MLSERVICE_HOST || 'http://localhost:8001';

      // Send POST request to ML service
      const response = await fetch(`${mlServiceHost}/ocr`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          pdf_url: urlData.signedUrl
        }),
      });

      if (!response.ok) {
        throw new Error(`ML service error: ${response.statusText}`);
      }

      const result = await response.json();
      console.log('Conversion started:', result);

      // Create a pending conversion record locally for immediate UI feedback
      const pendingConversion = {
        conversion_id: `pending-${result.id}`,
        file_id: file.file_id,
        job_id: result.id,
        job_completion: 0,
        status: 'pending',
        file_path: '',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString()
      };

      setConversions(prev => ({
        ...prev,
        [file.file_id]: pendingConversion
      }));

      // Start polling for this conversion
      startPolling(file.file_id);

      setError(`Conversion started! Task ID: ${result.id}`);

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
      // Completed - show download link and convert again option
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
          <button
            onClick={() => handleConvert(file)}
            className="text-green-600 hover:text-green-900 text-xs"
          >
            Convert Again
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
    <div className="max-w-6xl mx-auto">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold text-gray-800">My Files</h1>
        <button
          onClick={() => {
            fetchFiles();
            fetchConversions();
          }}
          className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors"
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
        <div className="bg-white shadow rounded-lg overflow-hidden">
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
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center">
                        <svg className="h-5 w-5 text-gray-400 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                        <div>
                          <div className="text-sm font-medium text-gray-900">
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
      )}
    </div>
  );
}