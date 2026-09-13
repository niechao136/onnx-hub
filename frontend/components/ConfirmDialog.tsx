'use client';

import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
} from '@mui/material';

export type DialogAction = 'stop' | 'restart' | 'redownload' | 'delete-key';

export interface ConfirmState {
  action: DialogAction;
  title: string;
  content: string;
  confirmText: string;
  danger?: boolean;
  payload?: unknown;
}

interface Props {
  state: ConfirmState | null;
  busy?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export default function ConfirmDialog({ state, busy, onCancel, onConfirm }: Props) {
  return (
    <Dialog open={Boolean(state)} onClose={onCancel} maxWidth="xs" fullWidth>
      <DialogTitle>{state?.title}</DialogTitle>
      <DialogContent>
        <DialogContentText>{state?.content}</DialogContentText>
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel} disabled={busy}>
          取消
        </Button>
        <Button
          onClick={onConfirm}
          variant="contained"
          color={state?.danger ? 'error' : 'primary'}
          disabled={busy}
        >
          {busy ? '处理中…' : (state?.confirmText ?? '确定')}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
