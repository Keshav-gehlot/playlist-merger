const loginButton = document.getElementById('loginButton');
const mergeButton = document.getElementById('mergeButton');
const playlistSection = document.getElementById('playlistSection');
const authSection = document.getElementById('authSection');
const playlistsContainer = document.getElementById('playlists');
const selectedCount = document.getElementById('selectedCount');
const statusMessage = document.getElementById('statusMessage');
const loader = document.getElementById('loader');
const playlistNameInput = document.getElementById('playlistName');

let playlists = [];

loginButton.addEventListener('click', () => {
  window.location.href = '/login';
});

mergeButton.addEventListener('click', async () => {
  const selected = getSelectedPlaylistIds();
  if (selected.length === 0) return;

  setLoading(true);
  showStatus('', false);

  try {
    const response = await fetch('/merge', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        playlist_ids: selected,
        new_playlist_name: playlistNameInput.value.trim() || 'Merged Playlist',
      }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || 'Merge failed');
    }

    showStatus(`✅ ${data.message}. Added ${data.tracks_added} unique tracks.`, false);
  } catch (error) {
    showStatus(`❌ ${error.message}`, true);
  } finally {
    setLoading(false);
  }
});

function getSelectedPlaylistIds() {
  return Array.from(document.querySelectorAll('input[name="playlist"]:checked')).map((input) => input.value);
}

function updateSelectionUI() {
  const selected = getSelectedPlaylistIds();
  selectedCount.textContent = `${selected.length} selected`;
  mergeButton.disabled = selected.length === 0;
}

function showStatus(message, isError) {
  if (!message) {
    statusMessage.classList.add('hidden');
    return;
  }

  statusMessage.classList.remove('hidden');
  statusMessage.classList.toggle('error', isError);
  statusMessage.textContent = message;
}

function setLoading(isLoading) {
  loader.classList.toggle('hidden', !isLoading);
  mergeButton.disabled = isLoading || getSelectedPlaylistIds().length === 0;
}

function renderPlaylists() {
  playlistsContainer.innerHTML = '';

  playlists.forEach((playlist) => {
    const card = document.createElement('label');
    card.className = 'playlist-card';

    card.innerHTML = `
      <input type="checkbox" name="playlist" value="${playlist.id}" />
      <div>
        <h3>${playlist.name}</h3>
        <div class="meta">${playlist.tracks_total} tracks · ${playlist.owner}</div>
      </div>
    `;

    const checkbox = card.querySelector('input');
    checkbox.addEventListener('change', updateSelectionUI);

    playlistsContainer.appendChild(card);
  });
}

async function loadPlaylists() {
  try {
    const response = await fetch('/playlists');
    if (response.status === 401) {
      authSection.classList.remove('hidden');
      playlistSection.classList.add('hidden');
      return;
    }

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || 'Failed to load playlists');
    }

    playlists = data.playlists || [];
    authSection.classList.add('hidden');
    playlistSection.classList.remove('hidden');
    renderPlaylists();
    updateSelectionUI();
  } catch (error) {
    showStatus(`❌ ${error.message}`, true);
  }
}

loadPlaylists();
