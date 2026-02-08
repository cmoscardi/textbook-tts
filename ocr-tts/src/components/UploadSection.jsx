import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { supabase } from '../lib/supabase.js';
import { useSession } from '../lib/SessionContext.jsx';

export default function UploadSection({ onUploadComplete }) {
  const { session } = useSession();
  const navigate = useNavigate();
  const [selectedFile, setSelectedFile] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState('');
  const [isParsing, setIsParsing] = useState(false);
  const [parsingProgress, setParsingProgress] = useState(0);
  const [parsingJobId, setParsingJobId] = useState(null);
  const [uploadedFileId, setUploadedFileId] = useState(null);
  const pollingIntervalRef = useRef(null);

  // Cleanup polling interval on unmount
  useEffect(() => {
    return () => {
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
      }
    };
  }, []);

  const handleFileSelect = (event) => {
    const file = event.target.files[0];
    if (!file) return;

    setSelectedFile(file);
    setUploadStatus('');
    setIsParsing(false);
    setParsingProgress(0);

    // Auto-start upload after file is selected
    setTimeout(() => handleUpload(file), 100);
  };

  const resetForm = () => {
    setSelectedFile(null);
    setIsUploading(false);
    setIsParsing(false);
    setParsingProgress(0);
    setParsingJobId(null);
    setUploadedFileId(null);
    // Reset file input
    const fileInput = document.getElementById('file-upload');
    if (fileInput) {
      fileInput.value = '';
    }
  };

  const startParsing = async (fileId) => {
    try {
      setIsParsing(true);
      setParsingProgress(0);
      setUploadStatus('Parsing PDF...');

      // Get the session token
      const { data: { session: currentSession } } = await supabase.auth.getSession();

      if (!currentSession) {
        throw new Error('Not authenticated');
      }

      // Call the parse-file Edge Function
      const { data, error } = await supabase.functions.invoke('parse-file', {
        body: { file_id: fileId },
        headers: {
          Authorization: `Bearer ${currentSession.access_token}`
        }
      });

      if (error) throw error;

      const jobId = data.id;
      setParsingJobId(jobId);

      // Start polling for parsing progress
      pollParsingProgress(jobId);
    } catch (error) {
      console.error('Error starting parsing:', error);
      setUploadStatus(`Parsing failed to start: ${error.message}`);
      setIsParsing(false);
    }
  };

  const pollParsingProgress = (jobId) => {
    // Clear any existing polling interval
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
    }

    // Poll immediately
    checkParsingStatus(jobId);

    // Then poll every 3 seconds
    pollingIntervalRef.current = setInterval(() => {
      checkParsingStatus(jobId);
    }, 3000);
  };


  const checkParsingStatus = async (jobId) => {
    try {
      const { data, error } = await supabase
        .from('file_parsings')
        .select('*')
        .eq('job_id', jobId)
        .single();

      if (error) {
        console.error('Error checking parsing status:', error);
        return;
      }

      if (data) {
        const { status, job_completion, file_id } = data;
        setParsingProgress(job_completion);

        if (status === 'completed') {
          setUploadStatus('Parsing complete! Opening file...');
          setIsParsing(false);
          clearInterval(pollingIntervalRef.current);
          pollingIntervalRef.current = null;

          // Call the callback to refresh the file list
          if (onUploadComplete) {
            onUploadComplete();
          }

          // Navigate to the file viewer page
          setTimeout(() => {
            navigate(`/app/view/${file_id}`);
          }, 500);
        } else if (status === 'failed') {
          setUploadStatus(`Parsing failed: ${data.error_message || 'Unknown error'}`);
          setIsParsing(false);
          clearInterval(pollingIntervalRef.current);
          pollingIntervalRef.current = null;
        } else if (status === 'running' && job_completion > 15) {
          // First page is ready — navigate to FileViewer for progressive display
          setUploadStatus('First page ready! Opening file...');
          setIsParsing(false);
          clearInterval(pollingIntervalRef.current);
          pollingIntervalRef.current = null;

          setTimeout(() => {
            navigate(`/app/view/${file_id}`);
          }, 500);
        } else {
          setUploadStatus(`Parsing in progress... ${job_completion}%`);
        }
      }
    } catch (error) {
      console.error('Error checking parsing status:', error);
    }
  };

  const handleUpload = async (file = null) => {
    const fileToUpload = file || selectedFile;

    if (!fileToUpload) {
      setUploadStatus('Please select a file first');
      return;
    }

    if (!session?.user) {
      setUploadStatus('User not authenticated');
      return;
    }

    setIsUploading(true);
    setUploadStatus('Uploading...');

    try {
      // Generate unique filename with timestamp
      const timestamp = Date.now();
      const fileExtension = fileToUpload.name.split('.').pop();
      const fileName = `${timestamp}_${fileToUpload.name}`;
      const filePath = `${session.user.id}/${fileName}`;

      // Upload file to Supabase storage
      const { data: uploadData, error: uploadError } = await supabase.storage
        .from('files')
        .upload(filePath, fileToUpload);

      if (uploadError) {
        throw uploadError;
      }

      // Calculate checksum
      const checksum = await calculateFileChecksum(fileToUpload);

      // Create database record
      const { data: insertData, error: dbError } = await supabase
        .from('files')
        .insert({
          user_id: session.user.id,
          file_name: fileToUpload.name,
          file_path: uploadData.path,
          file_size: fileToUpload.size,
          mime_type: fileToUpload.type,
          checksum: checksum
        })
        .select()
        .single();

      if (dbError) {
        // If database insert fails, try to clean up the uploaded file
        await supabase.storage.from('files').remove([filePath]);
        throw dbError;
      }

      const fileId = insertData.file_id;
      setUploadedFileId(fileId);
      setUploadStatus('File uploaded! Starting parsing...');
      setIsUploading(false);

      // Trigger parsing via Edge Function
      await startParsing(fileId);
    } catch (error) {
      console.error('Upload error:', error);
      setUploadStatus(`Upload failed: ${error.message}`);
    } finally {
      setIsUploading(false);
    }
  };

  // Simple checksum calculation function
  const calculateFileChecksum = async (file) => {
    const arrayBuffer = await file.arrayBuffer();
    const hashBuffer = await crypto.subtle.digest('SHA-256', arrayBuffer);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
  };

  return (
    <div className="max-w-4xl mx-auto bg-white rounded-lg shadow-md p-6">
      <h3 className="text-2xl font-bold text-gray-800 mb-6">Upload New File</h3>

      <div className="space-y-4">
        <div>
          <label htmlFor="file-upload" className="block text-sm font-medium text-gray-700 mb-2">
            Choose a PDF file (upload starts automatically)
          </label>
          <input
            id="file-upload"
            type="file"
            onChange={handleFileSelect}
            accept=".pdf"
            className="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
          />
        </div>

        {selectedFile && (
          <div className="text-sm text-gray-600">
            Selected: {selectedFile.name} ({(selectedFile.size / 1024 / 1024).toFixed(2)} MB)
          </div>
        )}

        {isParsing && (
          <div className="space-y-2">
            <div className="text-sm text-blue-700">
              Parsing PDF... {parsingProgress}%
            </div>
            <div className="w-full bg-gray-200 rounded-full h-2.5">
              <div
                className="bg-blue-600 h-2.5 rounded-full transition-all duration-300"
                style={{ width: `${parsingProgress}%` }}
              ></div>
            </div>
          </div>
        )}

        {uploadStatus && (
          <div className={`text-sm p-2 rounded ${
            uploadStatus.includes('complete') || uploadStatus.includes('ready') || uploadStatus.includes('Opening')
              ? 'text-green-700 bg-green-100'
              : uploadStatus.includes('failed')
              ? 'text-red-700 bg-red-100'
              : 'text-blue-700 bg-blue-100'
          }`}>
            {uploadStatus}
          </div>
        )}
      </div>
    </div>
  );
}
