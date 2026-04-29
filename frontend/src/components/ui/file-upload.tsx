"use client"

import { useState, useRef, useCallback } from "react"
import { toast } from "sonner"
import { Upload, FileText, X, Check, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { ProgressIndicator, PROFILES } from "@/components/ui/progress-indicator"
import { cn } from "@/lib/utils"

const DEFAULT_MAX_SIZE = 5 * 1024 * 1024

interface FileUploadProps {
  accept?: string
  maxSize?: number
  disabled?: boolean
  label?: string
  className?: string
  onFileSelect?: (file: File) => void
  onConfirm?: (file: File) => Promise<void>
}

export function FileUpload({
  accept = ".pdf,.doc,.docx",
  maxSize = DEFAULT_MAX_SIZE,
  disabled = false,
  label = "Upload file",
  className,
  onFileSelect,
  onConfirm,
}: FileUploadProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleClick = () => fileInputRef.current?.click()

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (file.size > maxSize) {
      toast.error(`File must be under ${Math.round(maxSize / 1024 / 1024)} MB`)
      return
    }
    setSelectedFile(file)
    onFileSelect?.(file)
  }

  const handleClear = () => {
    setSelectedFile(null)
    if (fileInputRef.current) fileInputRef.current.value = ""
  }

  const handleConfirm = async () => {
    if (!selectedFile || !onConfirm) return
    setIsLoading(true)
    try {
      await onConfirm(selectedFile)
      handleClear()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Upload failed")
    } finally {
      setIsLoading(false)
    }
  }

  const isDisabled = disabled || isLoading

  return (
    <div className={cn("w-full", className)}>
      <input
        ref={fileInputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={handleFileChange}
        disabled={isDisabled}
      />
      {selectedFile ? (
        <div className={cn("flex items-center gap-2 w-full", isLoading && "opacity-60")}>
          <div className="flex items-center flex-1 min-w-0 h-11 px-3 border rounded-md bg-background">
            <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
            <span className="ml-2 truncate text-sm">{selectedFile.name}</span>
            <button
              onClick={handleClear}
              disabled={isDisabled}
              className={cn("ml-auto shrink-0 p-1", isDisabled ? "cursor-not-allowed" : "cursor-pointer")}
            >
              <X className="h-4 w-4 text-muted-foreground hover:text-foreground transition-colors" />
            </button>
          </div>
          {onConfirm && (
            <Button size="icon" variant="outline" className="shrink-0" onClick={handleConfirm} disabled={isDisabled}>
              {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
            </Button>
          )}
        </div>
      ) : (
        <Button variant="outline" className="w-full h-11" onClick={handleClick} disabled={isDisabled}>
          <Upload className="h-4 w-4 mr-2" />
          {label}
        </Button>
      )}
    </div>
  )
}

const DEFAULT_MAX_FILES = 10

interface MultiFileUploadProps {
  accept?: string
  maxSize?: number
  maxFiles?: number
  disabled?: boolean
  label?: string
  className?: string
  defaultFiles?: File[]
  isLoading?: boolean
  isComplete?: boolean
  progressProfile?: keyof typeof PROFILES
  extraTimeMs?: number
  onFilesChange?: (files: File[]) => void
  onConfirm?: (files: File[]) => Promise<void>
  onProgressComplete?: () => void
}

export function MultiFileUpload({
  accept = "*",
  maxSize = DEFAULT_MAX_SIZE,
  maxFiles = DEFAULT_MAX_FILES,
  disabled = false,
  label = "Upload files",
  className,
  defaultFiles,
  isLoading: externalLoading,
  isComplete: externalComplete,
  progressProfile,
  extraTimeMs = 0,
  onFilesChange,
  onConfirm,
  onProgressComplete,
}: MultiFileUploadProps) {
  const [files, setFiles] = useState<File[]>(defaultFiles ?? [])
  const [internalLoading, setInternalLoading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const isLoading = externalLoading ?? internalLoading
  const isComplete = externalComplete ?? false

  const handleClick = () => fileInputRef.current?.click()

  const handleFiles = useCallback((newFiles: FileList | null) => {
    if (!newFiles) return

    const validFiles: File[] = []
    for (const file of Array.from(newFiles)) {
      if (file.size > maxSize) {
        toast.error(`${file.name} exceeds ${Math.round(maxSize / 1024 / 1024)} MB limit`)
        continue
      }
      if (files.length + validFiles.length >= maxFiles) {
        toast.error(`Maximum ${maxFiles} files allowed`)
        break
      }
      validFiles.push(file)
    }

    if (validFiles.length > 0) {
      const updated = [...files, ...validFiles]
      setFiles(updated)
      onFilesChange?.(updated)
    }
  }, [files, maxSize, maxFiles, onFilesChange])

  const handleRemoveFile = (index: number) => {
    const updated = files.filter((_, i) => i !== index)
    setFiles(updated)
    onFilesChange?.(updated)
  }

  const handleClearAll = () => {
    setFiles([])
    onFilesChange?.([])
    if (fileInputRef.current) fileInputRef.current.value = ""
  }

  const handleConfirm = async () => {
    if (files.length === 0 || !onConfirm) return
    if (externalLoading === undefined) setInternalLoading(true)
    try {
      await onConfirm(files)
      if (externalLoading === undefined) handleClearAll()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Upload failed")
    } finally {
      if (externalLoading === undefined) setInternalLoading(false)
    }
  }

  const isDisabled = disabled || isLoading
  const hasFiles = files.length > 0

  return (
    <div className={cn("w-full", className)}>
      <input
        ref={fileInputRef}
        type="file"
        accept={accept}
        multiple
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
        disabled={isDisabled}
      />

      {!hasFiles ? (
        <Button variant="outline" className="w-full h-11" onClick={handleClick} disabled={isDisabled}>
          <Upload className="h-4 w-4 mr-2" />
          {label}
        </Button>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">Files ({files.length})</span>
            <div className="flex gap-2">
              <Button variant="ghost" size="sm" onClick={handleClearAll} disabled={isDisabled}>
                Clear all
              </Button>
              <Button variant="outline" size="sm" onClick={handleClick} disabled={isDisabled}>
                <Upload className="h-4 w-4 mr-2" />
                Add more
              </Button>
            </div>
          </div>

          <div className="border rounded-lg overflow-hidden">
            <div className="divide-y max-h-[240px] overflow-y-auto">
              {files.map((file, index) => (
                <div
                  key={`${file.name}-${index}`}
                  className={cn("flex items-center gap-3 px-4 py-3 bg-background", isLoading && "opacity-60")}
                >
                  <FileText className="h-5 w-5 shrink-0 text-muted-foreground" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{file.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {(file.size / 1024).toFixed(1)} KB
                    </p>
                  </div>
                  <button
                    onClick={() => handleRemoveFile(index)}
                    disabled={isDisabled}
                    className={cn(
                      "p-1.5 rounded-md hover:bg-muted transition-colors",
                      isDisabled ? "cursor-not-allowed" : "cursor-pointer"
                    )}
                  >
                    <X className="h-4 w-4 text-muted-foreground" />
                  </button>
                </div>
              ))}
            </div>
          </div>

          {onConfirm && (
            isLoading && progressProfile ? (
              <ProgressIndicator
                profile={progressProfile}
                isActive={isLoading}
                isComplete={isComplete}
                extraTimeMs={extraTimeMs}
                onComplete={onProgressComplete}
              />
            ) : (
              <Button className="w-full" onClick={handleConfirm} disabled={isDisabled}>
                {isLoading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Check className="h-4 w-4 mr-2" />}
                {isLoading ? "Importing…" : "Confirm"}
              </Button>
            )
          )}
        </div>
      )}
    </div>
  )
}
