local util = require('lspconfig.util')
local lsp = vim.lsp

local server = {}

function server.start(init_result, config)
  local cmd = config.cmd
  local stdin = vim.loop.new_pipe()
  local stdout = vim.loop.new_pipe()
  local stderr = vim.loop.new_pipe()

  local handle, pid = vim.loop.spawn(cmd[1], {
    args = vim.list_slice(cmd, 2),
    stdio = { stdin, stdout, stderr },
  }, function(code)
    if code ~= 0 then
      vim.notify(string.format('alidistlint exited with code %d', code), vim.log.levels.ERROR)
    end
  end)

  if not handle then
    vim.notify('Failed to start alidistlint', vim.log.levels.ERROR)
    return
  end

  local client = lsp.start_client({
    handle = handle,
    cmd = cmd,
    root_dir = config.root_dir,
    capabilities = {
      textDocument = {
        diagnostic = {
          dynamicRegistration = true,
        },
      },
    },
  })

  if not client then
    vim.notify('Failed to create LSP client', vim.log.levels.ERROR)
    return
  end

  -- Handle diagnostics
  client.on_notification('textDocument/publishDiagnostics', function(args)
    local diagnostics = args.diagnostics
    local uri = args.uri
    local bufnr = vim.uri_to_bufnr(uri)
    
    if vim.fn.buf_loaded(bufnr) == 1 then
      vim.diagnostic.set(client.id, bufnr, diagnostics)
    end
  end)

  return client
end

return server 